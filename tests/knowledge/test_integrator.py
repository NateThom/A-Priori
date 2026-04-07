"""Tests for knowledge integration decision tree — AC traceability: Story 8.1.

AC:
- Given the librarian produces a concept named "PaymentValidator" that doesn't exist,
  when integration runs, then a new concept is created with created_by = "agent".
- Given an existing agent-created concept with description A, when the librarian
  produces a new analysis with description B that agrees with A, then last_verified
  is updated and confidence is boosted.
- Given an existing agent-created concept with description A, when the librarian
  produces contradictory description C, then both descriptions are preserved, the
  concept is flagged with needs-review, and the contradiction is logged.
- Given an existing agent-created concept with description A, when the librarian
  produces an extending description, then descriptions are merged (new information
  appended, existing preserved).
- Given an existing human-created concept, when the librarian produces analysis for
  the same code, then the human description is NOT overwritten.
- Given the librarian asserts an edge that already exists, when integration runs,
  then the edge's confidence is updated (take the higher value).
- Given the librarian asserts an edge contradicting an existing edge, when integration
  runs, then both are flagged with needs-review.
- Given any integration action, when it writes to the graph, then
  derived_from_code_version is stamped with the current git HEAD hash.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.storage.sqlite_store import SQLiteStore
from apriori.knowledge.integrator import IntegrationAction, IntegrationDecisionTree


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_GIT_HASH = "a" * 40  # 40-char hex, used as injected git hash provider


def _fake_git_hash() -> str:
    return FAKE_GIT_HASH


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "test.db")


@pytest.fixture()
def tree(store: SQLiteStore) -> IntegrationDecisionTree:
    return IntegrationDecisionTree(store, git_hash_provider=_fake_git_hash)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agent_concept(name: str, description: str, confidence: float = 0.5) -> Concept:
    return Concept(name=name, description=description, created_by="agent", confidence=confidence)


def _human_concept(name: str, description: str) -> Concept:
    return Concept(name=name, description=description, created_by="human", confidence=0.8)


# ---------------------------------------------------------------------------
# AC1: New concept creation
# ---------------------------------------------------------------------------

def test_new_concept_creates_with_agent_created_by(store: SQLiteStore, tree: IntegrationDecisionTree) -> None:
    """AC1: Given concept 'PaymentValidator' doesn't exist, when integration runs,
    then a new concept is created with created_by = 'agent'."""
    result = tree.integrate_concept("PaymentValidator", "Validates payment data structures.")

    assert result.action == IntegrationAction.CREATED
    saved = store.get_concept(result.concept.id)
    assert saved is not None
    assert saved.name == "PaymentValidator"
    assert saved.created_by == "agent"


# ---------------------------------------------------------------------------
# AC2: Agent concept — agree (last_verified updated, confidence boosted)
# ---------------------------------------------------------------------------

def test_agent_concept_agree_updates_last_verified_and_boosts_confidence(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC2: Given existing agent concept with description A and librarian produces
    an agreeing description B, then last_verified is set and confidence increases."""
    original = store.create_concept(
        _agent_concept("PaymentValidator", "Validates payment amounts and currency codes.", confidence=0.5)
    )
    assert original.last_verified is None

    # High-overlap description (agrees)
    result = tree.integrate_concept(
        "PaymentValidator",
        "Validates payment amounts and currency codes for transactions.",
    )

    assert result.action == IntegrationAction.VERIFIED
    updated = store.get_concept(original.id)
    assert updated is not None
    assert updated.last_verified is not None
    assert updated.confidence > 0.5


# ---------------------------------------------------------------------------
# AC3: Agent concept — contradiction (both preserved, needs-review flagged, logged)
# ---------------------------------------------------------------------------

def test_agent_concept_contradiction_flags_needs_review(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC3 (part 1): Given agent concept with description A and librarian produces
    contradictory description C, then the concept is flagged with 'needs-review'."""
    original = store.create_concept(
        _agent_concept("PaymentValidator", "Validates payment amounts and currency codes.")
    )

    # Low-overlap description (contradiction: < 30% key terms in common)
    result = tree.integrate_concept(
        "PaymentValidator",
        "Renders graphical user interface components for dashboard widgets.",
    )

    assert result.action == IntegrationAction.CONTRADICTED
    updated = store.get_concept(original.id)
    assert updated is not None
    assert "needs-review" in updated.labels


def test_agent_concept_contradiction_preserves_both_descriptions(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC3 (part 2): On contradiction, both original and new descriptions are preserved."""
    original_description = "Validates payment amounts and currency codes."
    original = store.create_concept(
        _agent_concept("PaymentValidator", original_description)
    )

    contradictory_description = "Renders graphical user interface components for dashboard widgets."
    tree.integrate_concept("PaymentValidator", contradictory_description)

    updated = store.get_concept(original.id)
    assert updated is not None
    # Original description preserved
    assert original_description in updated.description
    # Contradiction logged somewhere accessible
    assert updated.metadata is not None
    assert "contradictions" in updated.metadata


def test_agent_concept_contradiction_logs_contradiction(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC3 (part 3): On contradiction, the contradiction is logged in metadata."""
    store.create_concept(
        _agent_concept("PaymentValidator", "Validates payment amounts and currency codes.")
    )

    contradictory = "Renders graphical user interface components for dashboard widgets."
    tree.integrate_concept("PaymentValidator", contradictory)

    concepts = store.list_concepts()
    concept = next(c for c in concepts if c.name == "PaymentValidator")
    assert concept.metadata is not None
    contradictions = concept.metadata.get("contradictions", [])
    assert len(contradictions) == 1
    assert contradictions[0]["description"] == contradictory


# ---------------------------------------------------------------------------
# AC4: Agent concept — extend (new sentences appended, existing preserved)
# ---------------------------------------------------------------------------

def test_agent_concept_extend_merges_descriptions(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC4: Given agent concept with description A and librarian produces an extending
    description, then new information is appended and existing is preserved."""
    original_description = "Validates payment amounts and currency codes."
    original = store.create_concept(
        _agent_concept("PaymentValidator", original_description)
    )

    extending_description = (
        "Validates payment amounts and currency codes. "
        "Also enforces a minimum transaction floor of one cent."
    )
    result = tree.integrate_concept("PaymentValidator", extending_description)

    assert result.action == IntegrationAction.EXTENDED
    updated = store.get_concept(original.id)
    assert updated is not None
    # Original content preserved
    assert original_description in updated.description
    # New content appended
    assert "minimum transaction floor" in updated.description


# ---------------------------------------------------------------------------
# AC5: Human-created concept — supplementary only
# ---------------------------------------------------------------------------

def test_human_concept_description_not_overwritten(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC5 (part 1): Given human-created concept, when librarian produces analysis,
    the human description is NOT overwritten."""
    human_description = "Hand-crafted description by a human expert."
    original = store.create_concept(
        _human_concept("PaymentValidator", human_description)
    )

    result = tree.integrate_concept(
        "PaymentValidator",
        "Agent analysis of the payment validator component.",
    )

    assert result.action == IntegrationAction.SUPPLEMENTED
    updated = store.get_concept(original.id)
    assert updated is not None
    assert updated.description == human_description


def test_human_concept_agent_analysis_captured_as_supplementary(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC5 (part 2): Librarian analysis is captured as supplementary context in metadata."""
    store.create_concept(
        _human_concept("PaymentValidator", "Hand-crafted description by a human expert.")
    )

    agent_analysis = "Agent analysis of the payment validator component."
    tree.integrate_concept("PaymentValidator", agent_analysis)

    concepts = store.list_concepts()
    concept = next(c for c in concepts if c.name == "PaymentValidator")
    assert concept.metadata is not None
    supplementary = concept.metadata.get("agent_analyses", [])
    assert len(supplementary) == 1
    assert supplementary[0] == agent_analysis


# ---------------------------------------------------------------------------
# AC6: Edge — same type exists, confidence updated to higher value
# ---------------------------------------------------------------------------

def test_edge_same_type_updates_confidence_to_higher_value(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC6: Given an existing edge, when librarian asserts same edge with higher
    confidence, then edge's confidence is updated to the higher value."""
    source = store.create_concept(_agent_concept("SourceConcept", "Source."))
    target = store.create_concept(_agent_concept("TargetConcept", "Target."))

    existing_edge = store.create_edge(
        Edge(
            source_id=source.id,
            target_id=target.id,
            edge_type="depends-on",
            evidence_type="semantic",
            confidence=0.6,
        )
    )

    result = tree.integrate_edge(
        source_id=source.id,
        target_id=target.id,
        edge_type="depends-on",
        evidence_type="semantic",
        confidence=0.9,  # higher than existing 0.6
    )

    assert result.action == IntegrationAction.EDGE_UPDATED
    updated_edge = store.get_edge(existing_edge.id)
    assert updated_edge is not None
    assert updated_edge.confidence == 0.9


def test_edge_same_type_keeps_higher_confidence_when_new_is_lower(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC6: If existing confidence is already higher, keep the existing value."""
    source = store.create_concept(_agent_concept("SourceConcept", "Source."))
    target = store.create_concept(_agent_concept("TargetConcept", "Target."))

    existing_edge = store.create_edge(
        Edge(
            source_id=source.id,
            target_id=target.id,
            edge_type="depends-on",
            evidence_type="semantic",
            confidence=0.9,
        )
    )

    result = tree.integrate_edge(
        source_id=source.id,
        target_id=target.id,
        edge_type="depends-on",
        evidence_type="semantic",
        confidence=0.4,  # lower than existing 0.9
    )

    assert result.action == IntegrationAction.EDGE_UPDATED
    updated_edge = store.get_edge(existing_edge.id)
    assert updated_edge is not None
    assert updated_edge.confidence == 0.9


# ---------------------------------------------------------------------------
# AC7: Edge contradiction — different type, both flagged with needs-review
# ---------------------------------------------------------------------------

def test_edge_contradiction_flags_both_with_needs_review(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC7: Given existing edge A→B:depends-on, when librarian asserts A→B:supersedes,
    both are flagged with needs-review."""
    source = store.create_concept(_agent_concept("SourceConcept", "Source."))
    target = store.create_concept(_agent_concept("TargetConcept", "Target."))

    existing_edge = store.create_edge(
        Edge(
            source_id=source.id,
            target_id=target.id,
            edge_type="depends-on",
            evidence_type="semantic",
            confidence=0.8,
        )
    )

    result = tree.integrate_edge(
        source_id=source.id,
        target_id=target.id,
        edge_type="supersedes",  # different type = contradiction
        evidence_type="semantic",
        confidence=0.7,
    )

    assert result.action == IntegrationAction.EDGE_CONTRADICTED

    # Existing edge flagged
    updated_existing = store.get_edge(existing_edge.id)
    assert updated_existing is not None
    assert updated_existing.metadata is not None
    assert "needs-review" in updated_existing.metadata.get("labels", [])

    # New edge also created and flagged
    new_edge = result.edge
    assert new_edge.metadata is not None
    assert "needs-review" in new_edge.metadata.get("labels", [])


# ---------------------------------------------------------------------------
# AC8: Git version stamping on all writes
# ---------------------------------------------------------------------------

def test_new_concept_stamped_with_git_hash(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC8: Creating a new concept stamps derived_from_code_version with git HEAD."""
    result = tree.integrate_concept("NewConcept", "A brand new concept.")

    assert result.action == IntegrationAction.CREATED
    saved = store.get_concept(result.concept.id)
    assert saved is not None
    assert saved.derived_from_code_version == FAKE_GIT_HASH


def test_updated_concept_stamped_with_git_hash(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC8: Updating an existing concept stamps derived_from_code_version with git HEAD."""
    store.create_concept(
        _agent_concept("PaymentValidator", "Validates payment amounts and currency codes.")
    )

    tree.integrate_concept(
        "PaymentValidator",
        "Validates payment amounts and currency codes. Also handles refunds.",
    )

    concepts = store.list_concepts()
    concept = next(c for c in concepts if c.name == "PaymentValidator")
    assert concept.derived_from_code_version == FAKE_GIT_HASH


def test_edge_update_stamped_with_git_hash(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC8: Updating an edge stamps derived_from_code_version with git HEAD."""
    source = store.create_concept(_agent_concept("SourceConcept", "Source."))
    target = store.create_concept(_agent_concept("TargetConcept", "Target."))

    existing_edge = store.create_edge(
        Edge(
            source_id=source.id,
            target_id=target.id,
            edge_type="depends-on",
            evidence_type="semantic",
            confidence=0.5,
        )
    )

    tree.integrate_edge(
        source_id=source.id,
        target_id=target.id,
        edge_type="depends-on",
        evidence_type="semantic",
        confidence=0.9,
    )

    updated_edge = store.get_edge(existing_edge.id)
    assert updated_edge is not None
    assert updated_edge.derived_from_code_version == FAKE_GIT_HASH


def test_new_edge_stamped_with_git_hash(
    store: SQLiteStore, tree: IntegrationDecisionTree
) -> None:
    """AC8: Creating a new edge stamps derived_from_code_version with git HEAD."""
    source = store.create_concept(_agent_concept("SourceConcept", "Source."))
    target = store.create_concept(_agent_concept("TargetConcept", "Target."))

    result = tree.integrate_edge(
        source_id=source.id,
        target_id=target.id,
        edge_type="depends-on",
        evidence_type="semantic",
        confidence=0.7,
    )

    assert result.action == IntegrationAction.EDGE_CREATED
    saved_edge = store.get_edge(result.edge.id)
    assert saved_edge is not None
    assert saved_edge.derived_from_code_version == FAKE_GIT_HASH
