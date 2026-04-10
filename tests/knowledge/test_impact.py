"""Tests for semantic impact computation — AC traceability: Story 12.3.

AC:
- Given two concepts connected by a ``shares-assumption-about`` edge with
  confidence 0.8, when semantic impact is computed, then the target appears
  with confidence 0.8 and depth 1.
- Given a chain of semantic edges A->B (0.8) -> C (0.7), when traversal
  reaches C, then confidence is 0.8 * 0.7 = 0.56.
- Given a concept with no semantic edges, when impact is computed, then the
  semantic impact list is empty and the profile is flagged as "structural only".
- Given semantic graph traversal, when computing impact, then edges of type
  ``relates-to`` and ``owned-by`` are ignored.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apriori.knowledge.impact import ImpactComputer
from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.storage.sqlite_store import SQLiteStore


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "test.db")


def _concept(name: str) -> Concept:
    return Concept(name=name, description=f"{name} concept.", created_by="agent")


def _semantic_edge(source: Concept, target: Concept, edge_type: str, confidence: float) -> Edge:
    return Edge(
        source_id=source.id,
        target_id=target.id,
        edge_type=edge_type,
        evidence_type="semantic",
        confidence=confidence,
    )


def test_ac1_shares_assumption_edge_yields_depth_1_and_edge_confidence(store: SQLiteStore) -> None:
    """AC1: shares-assumption-about edge appears at depth=1 with its confidence."""
    source = store.create_concept(_concept("Source"))
    target = store.create_concept(_concept("Target"))
    edge = store.create_edge(
        _semantic_edge(source, target, edge_type="shares-assumption-about", confidence=0.8)
    )

    computer = ImpactComputer(store)
    semantic = computer.compute_semantic_impact(source.id)

    assert len(semantic) == 1
    assert semantic[0].target_concept_id == target.id
    assert semantic[0].confidence == pytest.approx(0.8)
    assert semantic[0].depth == 1
    assert semantic[0].relationship_path == [str(edge.id)]


def test_ac2_confidence_multiplies_across_semantic_path(store: SQLiteStore) -> None:
    """AC2: confidence for A->B->C is multiplicative (0.8 * 0.7 = 0.56)."""
    concept_a = store.create_concept(_concept("A"))
    concept_b = store.create_concept(_concept("B"))
    concept_c = store.create_concept(_concept("C"))
    store.create_edge(
        _semantic_edge(concept_a, concept_b, edge_type="shares-assumption-about", confidence=0.8)
    )
    store.create_edge(
        _semantic_edge(concept_b, concept_c, edge_type="implements", confidence=0.7)
    )

    computer = ImpactComputer(store)
    semantic = computer.compute_semantic_impact(concept_a.id)
    by_target = {entry.target_concept_id: entry for entry in semantic}

    assert concept_c.id in by_target
    assert by_target[concept_c.id].depth == 2
    assert by_target[concept_c.id].confidence == pytest.approx(0.56)


def test_ac3_no_semantic_edges_marks_profile_structural_only(store: SQLiteStore) -> None:
    """AC3: no semantic impact entries sets structural_only=True on the profile."""
    source = store.create_concept(_concept("Source"))
    target = store.create_concept(_concept("Target"))
    store.create_edge(
        Edge(
            source_id=source.id,
            target_id=target.id,
            edge_type="calls",
            evidence_type="structural",
            confidence=1.0,
        )
    )

    computer = ImpactComputer(store)
    profile = computer.compute_profile(source.id)

    assert profile.semantic_impact == []
    assert profile.structural_only is True


def test_ac4_relates_to_and_owned_by_edges_are_ignored(store: SQLiteStore) -> None:
    """AC4: relates-to and owned-by do not contribute to semantic impact traversal."""
    source = store.create_concept(_concept("Source"))
    ignored_relates = store.create_concept(_concept("RelatesIgnored"))
    ignored_owned = store.create_concept(_concept("OwnedIgnored"))
    included = store.create_concept(_concept("Included"))

    store.create_edge(_semantic_edge(source, ignored_relates, edge_type="relates-to", confidence=0.9))
    store.create_edge(_semantic_edge(source, ignored_owned, edge_type="owned-by", confidence=0.95))
    store.create_edge(_semantic_edge(source, included, edge_type="depends-on", confidence=0.6))

    computer = ImpactComputer(store)
    semantic = computer.compute_semantic_impact(source.id)
    target_ids = {entry.target_concept_id for entry in semantic}

    assert included.id in target_ids
    assert ignored_relates.id not in target_ids
    assert ignored_owned.id not in target_ids
