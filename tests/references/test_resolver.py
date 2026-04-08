"""Tests for the code reference repair chain (Story 3.7, PRD §5.2).

AC traceability:
- AC1: valid symbol → symbol lookup succeeds, content hash verified against store
- AC2: symbol renamed, content unchanged → content hash path succeeds, symbol updated
- AC3: symbol renamed + content changed → semantic anchor invoked, returns unresolved (Phase 1)
- AC4: all three fail → code reference marked is_unresolved=True, parent labeled needs-review

Additional coverage:
- Symbol found but hash doesn't match → still resolved_by_symbol (hash_verified=False)
- Multiple code references: mixed results — only failing ones marked unresolved
- resolve_code_reference telemetry: method field populated correctly for all paths
"""

import hashlib
from pathlib import Path
from typing import Optional

import pytest

from apriori.models.concept import CodeReference, Concept
from apriori.references.resolver import (
    ResolutionMethod,
    ResolutionResult,
    resolve_code_reference,
    resolve_concept_references,
)
from apriori.storage.sqlite_store import SQLiteStore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HASH_A = hashlib.sha256(b"original content A").hexdigest()
HASH_B = hashlib.sha256(b"different content B").hexdigest()
SYMBOL_OLD = "src/app.py::my_function"
SYMBOL_NEW = "src/app.py::renamed_function"
ANCHOR = "python function 'my_function' at src/app.py:1-5"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "test.db")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_structural_concept(
    symbol: str,
    content_hash: str,
    store: SQLiteStore,
    anchor: str = ANCHOR,
) -> Concept:
    """Create a concept in the store where concept.name == symbol (graph builder convention)."""
    code_ref = CodeReference(
        symbol=symbol,
        file_path="src/app.py",
        content_hash=content_hash,
        semantic_anchor=anchor,
    )
    concept = Concept(
        name=symbol,  # FQN IS the concept name per graph builder convention
        description=f"Structural concept for {symbol}",
        created_by="agent",
        code_references=[code_ref],
    )
    return store.create_concept(concept)


def _make_code_ref(
    symbol: str,
    content_hash: str,
    anchor: str = ANCHOR,
) -> CodeReference:
    return CodeReference(
        symbol=symbol,
        file_path="src/app.py",
        content_hash=content_hash,
        semantic_anchor=anchor,
    )


# ---------------------------------------------------------------------------
# AC1: valid symbol → symbol lookup succeeds
# ---------------------------------------------------------------------------


def test_ac1_symbol_lookup_succeeds(store: SQLiteStore) -> None:
    """AC1: Given a code reference with a valid symbol, symbol lookup succeeds
    and the content hash is verified against the current code in the store."""
    # Given: structural concept in store matching the code reference exactly
    canonical = _make_structural_concept(SYMBOL_OLD, HASH_A, store)
    code_ref = _make_code_ref(SYMBOL_OLD, HASH_A)

    # When: resolved
    result = resolve_code_reference(code_ref, store)

    # Then: symbol lookup path taken
    assert result.method == ResolutionMethod.SYMBOL
    assert result.resolved_concept_id == canonical.id
    # And: content hash verified
    assert result.hash_verified is True


def test_ac1_symbol_found_hash_mismatch_still_symbol_path(store: SQLiteStore) -> None:
    """AC1 variant: symbol found but content changed → still SYMBOL path, hash_verified=False."""
    # Given: concept with same symbol but different hash (content changed)
    _make_structural_concept(SYMBOL_OLD, HASH_B, store)
    code_ref = _make_code_ref(SYMBOL_OLD, HASH_A)

    result = resolve_code_reference(code_ref, store)

    assert result.method == ResolutionMethod.SYMBOL
    assert result.hash_verified is False


# ---------------------------------------------------------------------------
# AC2: symbol renamed, content unchanged → content hash fallback
# ---------------------------------------------------------------------------


def test_ac2_content_hash_fallback_when_symbol_renamed(store: SQLiteStore) -> None:
    """AC2: Given symbol was renamed but content is unchanged, symbol lookup fails
    and the content hash is used to locate the code."""
    # Given: structural concept with SYMBOL_NEW (renamed), same content hash
    canonical = _make_structural_concept(SYMBOL_NEW, HASH_A, store)
    # Code reference still has old symbol
    code_ref = _make_code_ref(SYMBOL_OLD, HASH_A)

    # When: resolved (no concept named SYMBOL_OLD in store)
    result = resolve_code_reference(code_ref, store)

    # Then: content hash path taken
    assert result.method == ResolutionMethod.CONTENT_HASH
    assert result.resolved_concept_id == canonical.id
    assert result.symbol_updated is True


def test_ac2_symbol_updated_in_store(store: SQLiteStore) -> None:
    """AC2: When content hash resolves, resolve_concept_references updates the stale symbol."""
    # Given: canonical concept with SYMBOL_NEW in store
    _make_structural_concept(SYMBOL_NEW, HASH_A, store)

    # Parent concept has stale code reference pointing to SYMBOL_OLD
    stale_ref = _make_code_ref(SYMBOL_OLD, HASH_A)
    parent = Concept(
        name="UserAuth",
        description="Semantic concept",
        created_by="agent",
        code_references=[stale_ref],
    )
    parent = store.create_concept(parent)

    # When: resolve_concept_references
    results = resolve_concept_references(parent, store)

    # Then: resolved by hash
    assert results[0].method == ResolutionMethod.CONTENT_HASH

    # And: symbol updated to SYMBOL_NEW in persisted concept
    updated_parent = store.get_concept(parent.id)
    assert updated_parent is not None
    assert updated_parent.code_references[0].symbol == SYMBOL_NEW


def test_ac2_does_not_resolve_parent_against_itself(store: SQLiteStore) -> None:
    """Content hash scan must not resolve a concept against its own stale reference."""
    # Given: only the parent concept in the store (no canonical structural concept)
    stale_ref = _make_code_ref(SYMBOL_OLD, HASH_A)
    parent = Concept(
        name="UserAuth",
        description="Semantic concept",
        created_by="agent",
        code_references=[stale_ref],
    )
    parent = store.create_concept(parent)

    # When: resolve_concept_references (would wrongly self-resolve without exclusion)
    results = resolve_concept_references(parent, store)

    # Then: not resolved (self-reference excluded → falls through to unresolved)
    assert results[0].method == ResolutionMethod.UNRESOLVED


# ---------------------------------------------------------------------------
# AC3: both symbol and hash fail → semantic anchor → Phase 1 returns UNRESOLVED
# ---------------------------------------------------------------------------


def test_ac3_semantic_anchor_invoked_returns_unresolved(store: SQLiteStore) -> None:
    """AC3: When both symbol and hash lookups fail, the semantic anchor path is
    invoked. In Phase 1, it returns unresolved immediately (no LLM call)."""
    # Given: no relevant concepts in store
    code_ref = _make_code_ref(SYMBOL_OLD, HASH_A)

    # When: both symbol and hash fail
    result = resolve_code_reference(code_ref, store)

    # Then: semantic anchor path → UNRESOLVED
    assert result.method == ResolutionMethod.UNRESOLVED
    assert result.resolved_concept_id is None


def test_ac3_unresolved_when_hash_wrong_and_symbol_missing(store: SQLiteStore) -> None:
    """AC3: Symbol renamed AND content changed → unresolved (semantic anchor dormant)."""
    # Given: concept with SYMBOL_NEW but HASH_B (different content)
    _make_structural_concept(SYMBOL_NEW, HASH_B, store)
    # Code ref has SYMBOL_OLD and HASH_A — neither matches
    code_ref = _make_code_ref(SYMBOL_OLD, HASH_A)

    result = resolve_code_reference(code_ref, store)

    assert result.method == ResolutionMethod.UNRESOLVED


# ---------------------------------------------------------------------------
# AC4: all fail → code reference marked unresolved, concept labeled needs-review
# ---------------------------------------------------------------------------


def test_ac4_code_reference_marked_unresolved(store: SQLiteStore) -> None:
    """AC4: When resolution fails, the code reference is marked is_unresolved=True."""
    stale_ref = _make_code_ref(SYMBOL_OLD, HASH_A)
    parent = Concept(
        name="UserAuth",
        description="Semantic concept",
        created_by="agent",
        code_references=[stale_ref],
    )
    parent = store.create_concept(parent)

    results = resolve_concept_references(parent, store)

    assert results[0].method == ResolutionMethod.UNRESOLVED

    updated_parent = store.get_concept(parent.id)
    assert updated_parent is not None
    assert updated_parent.code_references[0].is_unresolved is True


def test_ac4_parent_concept_labeled_needs_review(store: SQLiteStore) -> None:
    """AC4: When all resolution methods fail, the parent concept is labeled needs-review."""
    stale_ref = _make_code_ref(SYMBOL_OLD, HASH_A)
    parent = Concept(
        name="UserAuth",
        description="Semantic concept",
        created_by="agent",
        code_references=[stale_ref],
    )
    parent = store.create_concept(parent)

    resolve_concept_references(parent, store)

    updated_parent = store.get_concept(parent.id)
    assert updated_parent is not None
    assert "needs-review" in updated_parent.labels


def test_ac4_needs_review_not_added_when_resolved(store: SQLiteStore) -> None:
    """needs-review label must NOT be added when resolution succeeds."""
    _make_structural_concept(SYMBOL_OLD, HASH_A, store)

    code_ref = _make_code_ref(SYMBOL_OLD, HASH_A)
    parent = Concept(
        name="UserAuth",
        description="Semantic concept",
        created_by="agent",
        code_references=[code_ref],
    )
    parent = store.create_concept(parent)

    results = resolve_concept_references(parent, store)

    assert results[0].method == ResolutionMethod.SYMBOL
    updated_parent = store.get_concept(parent.id)
    assert updated_parent is not None
    assert "needs-review" not in updated_parent.labels


# ---------------------------------------------------------------------------
# Additional: independent step testing
# ---------------------------------------------------------------------------


def test_each_step_tested_independently_symbol(store: SQLiteStore) -> None:
    """Symbol lookup is independent of content hash scan (step 1 returns before step 2)."""
    # Both symbol match AND hash match exist — symbol step wins
    canonical = _make_structural_concept(SYMBOL_OLD, HASH_A, store)
    code_ref = _make_code_ref(SYMBOL_OLD, HASH_A)

    result = resolve_code_reference(code_ref, store)

    # Symbol takes priority
    assert result.method == ResolutionMethod.SYMBOL
    assert result.resolved_concept_id == canonical.id


def test_each_step_tested_independently_content_hash(store: SQLiteStore) -> None:
    """Content hash step is independent: only runs after symbol lookup fails."""
    # No symbol match, but hash match exists
    _make_structural_concept(SYMBOL_NEW, HASH_A, store)
    code_ref = _make_code_ref(SYMBOL_OLD, HASH_A)

    result = resolve_code_reference(code_ref, store)

    assert result.method == ResolutionMethod.CONTENT_HASH


def test_each_step_tested_independently_unresolved(store: SQLiteStore) -> None:
    """Unresolved is only returned after all three steps are attempted."""
    code_ref = _make_code_ref(SYMBOL_OLD, HASH_A)

    result = resolve_code_reference(code_ref, store)

    assert result.method == ResolutionMethod.UNRESOLVED


# ---------------------------------------------------------------------------
# Additional: telemetry field completeness
# ---------------------------------------------------------------------------


def test_resolution_result_includes_method_for_telemetry(store: SQLiteStore) -> None:
    """All resolution paths return a ResolutionResult with a populated method field."""
    # SYMBOL path
    _make_structural_concept(SYMBOL_OLD, HASH_A, store)
    r1 = resolve_code_reference(_make_code_ref(SYMBOL_OLD, HASH_A), store)
    assert isinstance(r1.method, ResolutionMethod)

    # CONTENT_HASH path
    _make_structural_concept(SYMBOL_NEW, HASH_B, store)
    r2 = resolve_code_reference(_make_code_ref("src/app.py::other", HASH_B), store)
    assert isinstance(r2.method, ResolutionMethod)

    # UNRESOLVED path (no match for this hash)
    unique_hash = hashlib.sha256(b"unique content xyz").hexdigest()
    r3 = resolve_code_reference(_make_code_ref("src/app.py::gone", unique_hash), store)
    assert r3.method == ResolutionMethod.UNRESOLVED


# ---------------------------------------------------------------------------
# Additional: graceful degradation — no code references → empty results
# ---------------------------------------------------------------------------


def test_graceful_degradation_no_code_references(store: SQLiteStore) -> None:
    """resolve_concept_references returns empty list when concept has no code references."""
    concept = Concept(
        name="EmptyConcept",
        description="No code references",
        created_by="agent",
        code_references=[],
    )
    concept = store.create_concept(concept)

    results = resolve_concept_references(concept, store)

    assert results == []


# ---------------------------------------------------------------------------
# Additional: multiple code references — mixed resolution
# ---------------------------------------------------------------------------


def test_multiple_code_refs_mixed_results(store: SQLiteStore) -> None:
    """Multiple code references on one concept: each resolved independently."""
    # One resolvable (symbol match), one not (no match)
    _make_structural_concept(SYMBOL_OLD, HASH_A, store)

    ref_good = _make_code_ref(SYMBOL_OLD, HASH_A)
    ref_bad = _make_code_ref("src/gone.py::deleted_function", HASH_B)

    parent = Concept(
        name="UserAuth",
        description="Semantic concept",
        created_by="agent",
        code_references=[ref_good, ref_bad],
    )
    parent = store.create_concept(parent)

    results = resolve_concept_references(parent, store)

    assert len(results) == 2
    assert results[0].method == ResolutionMethod.SYMBOL
    assert results[1].method == ResolutionMethod.UNRESOLVED

    updated_parent = store.get_concept(parent.id)
    assert updated_parent is not None
    # Good reference: not marked unresolved
    assert updated_parent.code_references[0].is_unresolved is False
    # Bad reference: marked unresolved
    assert updated_parent.code_references[1].is_unresolved is True
    # Parent labeled needs-review because at least one failed
    assert "needs-review" in updated_parent.labels
