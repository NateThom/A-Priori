"""Tests for staleness detection — AC traceability: Story 8.2.

AC:
- AC1: Given a concept derived from commit A, when the referenced code is
  modified in commit B, then the concept is labeled 'stale'.
- AC2: Given a concept derived from commit B and the current HEAD is also B,
  when staleness detection runs, then the concept is NOT labeled stale.
- AC3: Given a stale concept, when the librarian re-verifies it, then the
  'stale' label is removed and 'derived_from_code_version' is updated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apriori.models.concept import Concept, CodeReference
from apriori.storage.sqlite_store import SQLiteStore
from apriori.knowledge.integrator import IntegrationAction, IntegrationDecisionTree
from apriori.knowledge.staleness import StalenessDetector


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMMIT_A = "a" * 40  # concept was derived at this commit
COMMIT_B = "b" * 40  # current HEAD (code was modified here)
_CONTENT_HASH = "c" * 64  # valid SHA-256 placeholder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "test.db")


def _make_code_ref(file_path: str) -> CodeReference:
    return CodeReference(
        symbol="some_function",
        file_path=file_path,
        content_hash=_CONTENT_HASH,
        semantic_anchor="anchor",
    )


def _agent_concept_at(
    name: str,
    description: str,
    commit: str,
    file_paths: list[str] | None = None,
) -> Concept:
    refs = [_make_code_ref(fp) for fp in (file_paths or [])]
    return Concept(
        name=name,
        description=description,
        created_by="agent",
        derived_from_code_version=commit,
        code_references=refs,
    )


# ---------------------------------------------------------------------------
# Helpers for injecting git providers into tests
# ---------------------------------------------------------------------------


def _hash_provider(h: str):
    """Return a callable that always returns the given hash."""
    def provider() -> str:
        return h
    return provider


def _files_provider(changed: set[str]):
    """Return a callable that returns the given set of changed files."""
    def provider(old_hash: str, new_hash: str) -> set[str]:  # noqa: ARG001
        return changed
    return provider


# ---------------------------------------------------------------------------
# AC1: Concept derived from commit A, referenced file changed in commit B
# ---------------------------------------------------------------------------


def test_ac1_concept_is_labeled_stale_when_referenced_file_changed(
    store: SQLiteStore,
) -> None:
    """AC1: Given concept derived from commit A, when referenced code modified
    in commit B, then the concept is labeled 'stale'."""
    concept = store.create_concept(
        _agent_concept_at(
            "PaymentValidator",
            "Validates payment data.",
            COMMIT_A,
            file_paths=["src/payment.py"],
        )
    )
    assert "stale" not in concept.labels

    detector = StalenessDetector(
        store,
        git_hash_provider=_hash_provider(COMMIT_B),
        changed_files_provider=_files_provider({"src/payment.py"}),
    )
    stale = detector.detect_and_mark_stale()

    assert len(stale) == 1
    assert stale[0].id == concept.id
    assert "stale" in stale[0].labels

    # Persisted in the store
    saved = store.get_concept(concept.id)
    assert saved is not None
    assert "stale" in saved.labels


def test_ac1_concept_with_multiple_refs_is_stale_when_any_file_changed(
    store: SQLiteStore,
) -> None:
    """AC1 variant: A concept with two code references is stale when one changes."""
    concept = store.create_concept(
        _agent_concept_at(
            "OrderProcessor",
            "Processes customer orders.",
            COMMIT_A,
            file_paths=["src/orders.py", "src/inventory.py"],
        )
    )

    detector = StalenessDetector(
        store,
        git_hash_provider=_hash_provider(COMMIT_B),
        # Only one of the two files changed
        changed_files_provider=_files_provider({"src/inventory.py"}),
    )
    stale = detector.detect_and_mark_stale()

    assert len(stale) == 1
    assert "stale" in stale[0].labels


# ---------------------------------------------------------------------------
# AC2: Concept derived from current HEAD — NOT stale
# ---------------------------------------------------------------------------


def test_ac2_concept_at_current_head_is_not_stale(
    store: SQLiteStore,
) -> None:
    """AC2: Given concept derived from commit B and current HEAD is B, the
    concept is NOT labeled stale."""
    concept = store.create_concept(
        _agent_concept_at(
            "PaymentValidator",
            "Validates payment data.",
            COMMIT_B,  # same as current HEAD
            file_paths=["src/payment.py"],
        )
    )

    detector = StalenessDetector(
        store,
        git_hash_provider=_hash_provider(COMMIT_B),
        changed_files_provider=_files_provider({"src/payment.py"}),
    )
    stale = detector.detect_and_mark_stale()

    assert stale == []
    saved = store.get_concept(concept.id)
    assert saved is not None
    assert "stale" not in saved.labels


def test_ac2_concept_with_different_commit_but_no_file_change_is_not_stale(
    store: SQLiteStore,
) -> None:
    """AC2 variant: Concept at old commit, but referenced file unchanged — not stale."""
    store.create_concept(
        _agent_concept_at(
            "OrderProcessor",
            "Processes orders.",
            COMMIT_A,
            file_paths=["src/orders.py"],
        )
    )

    detector = StalenessDetector(
        store,
        git_hash_provider=_hash_provider(COMMIT_B),
        # The referenced file did NOT change
        changed_files_provider=_files_provider({"src/unrelated.py"}),
    )
    stale = detector.detect_and_mark_stale()

    assert stale == []


def test_concept_without_code_references_is_not_stale(
    store: SQLiteStore,
) -> None:
    """Concept with no code_references cannot be compared to changed files — skip."""
    store.create_concept(
        _agent_concept_at(
            "AbstractConcept",
            "No file references.",
            COMMIT_A,
            file_paths=[],  # empty
        )
    )

    detector = StalenessDetector(
        store,
        git_hash_provider=_hash_provider(COMMIT_B),
        changed_files_provider=_files_provider({"src/anything.py"}),
    )
    stale = detector.detect_and_mark_stale()

    assert stale == []


def test_concept_without_derived_from_version_is_not_stale(
    store: SQLiteStore,
) -> None:
    """Concept with no derived_from_code_version cannot be compared — skip."""
    concept = Concept(
        name="Unversioned",
        description="Never versioned.",
        created_by="agent",
        derived_from_code_version=None,
        code_references=[_make_code_ref("src/foo.py")],
    )
    store.create_concept(concept)

    detector = StalenessDetector(
        store,
        git_hash_provider=_hash_provider(COMMIT_B),
        changed_files_provider=_files_provider({"src/foo.py"}),
    )
    stale = detector.detect_and_mark_stale()

    assert stale == []


# ---------------------------------------------------------------------------
# AC3: Stale concept re-verified → stale label removed, version updated
# ---------------------------------------------------------------------------


def test_ac3_re_verification_removes_stale_label(
    store: SQLiteStore,
) -> None:
    """AC3: Given a stale concept, when the librarian re-verifies it, the
    'stale' label is removed and derived_from_code_version is updated."""
    # Create a concept already labeled stale at commit A
    stale_concept = Concept(
        name="PaymentValidator",
        description="Validates payment data.",
        created_by="agent",
        derived_from_code_version=COMMIT_A,
        labels={"stale"},
        code_references=[_make_code_ref("src/payment.py")],
    )
    store.create_concept(stale_concept)

    # Librarian re-verifies (agrees) at commit B
    tree = IntegrationDecisionTree(
        store,
        git_hash_provider=_hash_provider(COMMIT_B),
    )
    result = tree.integrate_concept(
        "PaymentValidator",
        "Validates payment data.",  # same description → VERIFIED action
    )

    assert result.action == IntegrationAction.VERIFIED
    saved = store.get_concept(result.concept.id)
    assert saved is not None
    assert "stale" not in saved.labels
    assert saved.derived_from_code_version == COMMIT_B


def test_ac3_extension_also_removes_stale_label(
    store: SQLiteStore,
) -> None:
    """AC3 variant: When re-verification extends the description, stale is also removed."""
    stale_concept = Concept(
        name="OrderProcessor",
        description="Processes customer orders.",
        created_by="agent",
        derived_from_code_version=COMMIT_A,
        labels={"stale", "auto-generated"},
        code_references=[_make_code_ref("src/orders.py")],
    )
    store.create_concept(stale_concept)

    tree = IntegrationDecisionTree(
        store,
        git_hash_provider=_hash_provider(COMMIT_B),
    )
    result = tree.integrate_concept(
        "OrderProcessor",
        # Extra sentence not in original → EXTENDED action
        "Processes customer orders. Also handles order cancellations.",
    )

    assert result.action == IntegrationAction.EXTENDED
    saved = store.get_concept(result.concept.id)
    assert saved is not None
    assert "stale" not in saved.labels
    assert "auto-generated" in saved.labels  # other labels preserved
    assert saved.derived_from_code_version == COMMIT_B


# ---------------------------------------------------------------------------
# Idempotency: running detector twice doesn't change state
# ---------------------------------------------------------------------------


def test_detection_is_idempotent(store: SQLiteStore) -> None:
    """Running detect_and_mark_stale twice produces the same result."""
    store.create_concept(
        _agent_concept_at(
            "PaymentValidator",
            "Validates payment data.",
            COMMIT_A,
            file_paths=["src/payment.py"],
        )
    )

    detector = StalenessDetector(
        store,
        git_hash_provider=_hash_provider(COMMIT_B),
        changed_files_provider=_files_provider({"src/payment.py"}),
    )

    first_run = detector.detect_and_mark_stale()
    second_run = detector.detect_and_mark_stale()

    assert len(first_run) == 1
    # Already stale; second run returns it again (stale was already set)
    assert len(second_run) == 1
    saved = store.get_concept(first_run[0].id)
    assert saved is not None
    assert saved.labels.count("stale") if isinstance(saved.labels, list) else "stale" in saved.labels


# ---------------------------------------------------------------------------
# Multiple concepts — only changed ones go stale
# ---------------------------------------------------------------------------


def test_only_concepts_with_changed_files_are_marked_stale(
    store: SQLiteStore,
) -> None:
    """Only the concept whose referenced file changed is labeled stale."""
    c1 = store.create_concept(
        _agent_concept_at(
            "PaymentValidator",
            "Validates payment data.",
            COMMIT_A,
            file_paths=["src/payment.py"],
        )
    )
    c2 = store.create_concept(
        _agent_concept_at(
            "OrderProcessor",
            "Processes orders.",
            COMMIT_A,
            file_paths=["src/orders.py"],
        )
    )

    detector = StalenessDetector(
        store,
        git_hash_provider=_hash_provider(COMMIT_B),
        # Only src/payment.py changed
        changed_files_provider=_files_provider({"src/payment.py"}),
    )
    stale = detector.detect_and_mark_stale()

    stale_ids = {c.id for c in stale}
    assert c1.id in stale_ids
    assert c2.id not in stale_ids

    # c2 should not be stale in store
    saved_c2 = store.get_concept(c2.id)
    assert saved_c2 is not None
    assert "stale" not in saved_c2.labels
