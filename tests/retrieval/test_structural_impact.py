"""Tests for structural impact computation — AC traceability: Story 12.2.

AC1: Given a function called by 3 other functions, when structural impact is
     computed, then all 3 callers appear with confidence = 1.0 and depth = 1.

AC2: Given a class inherited by 2 subclasses, each [calling / called by] 1
     additional function, when structural impact is computed with max_depth=2,
     then 4 concepts appear (2 at depth 1, 2 at depth 2).

AC3: Given the traversal, when an ImpactEntry is produced, then it includes
     relationship_path and a rationale.

AC4: Given a concept with no structural dependents, when impact is computed,
     then the structural impact list is empty.
"""

from __future__ import annotations

import uuid
from typing import Optional

import pytest

from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.models.impact import ImpactEntry
from apriori.models.librarian_activity import LibrarianActivity
from apriori.models.review_outcome import ReviewOutcome
from apriori.models.work_item import FailureRecord, WorkItem
from apriori.retrieval.structural_impact import compute_structural_impact


# ---------------------------------------------------------------------------
# Minimal in-memory store for tests
# ---------------------------------------------------------------------------


class _InMemoryStore:
    """Minimal in-memory KnowledgeStore for structural impact tests.

    Only implements the subset of methods used by compute_structural_impact:
    list_edges(target_id=...) and create_concept/create_edge helpers.
    """

    def __init__(self) -> None:
        self._concepts: dict[uuid.UUID, Concept] = {}
        self._edges: dict[uuid.UUID, Edge] = {}

    # --- Concept CRUD ---

    def create_concept(self, concept: Concept) -> Concept:
        self._concepts[concept.id] = concept
        return concept

    def get_concept(self, concept_id: uuid.UUID) -> Optional[Concept]:
        return self._concepts.get(concept_id)

    def update_concept(self, concept: Concept) -> Concept:
        self._concepts[concept.id] = concept
        return concept

    def delete_concept(self, concept_id: uuid.UUID) -> None:
        self._concepts.pop(concept_id, None)

    def list_concepts(self, labels: Optional[set[str]] = None) -> list[Concept]:
        concepts = list(self._concepts.values())
        if labels:
            concepts = [c for c in concepts if labels & c.labels]
        return concepts

    # --- Edge CRUD ---

    def create_edge(self, edge: Edge) -> Edge:
        self._edges[edge.id] = edge
        return edge

    def get_edge(self, edge_id: uuid.UUID) -> Optional[Edge]:
        return self._edges.get(edge_id)

    def update_edge(self, edge: Edge) -> Edge:
        self._edges[edge.id] = edge
        return edge

    def delete_edge(self, edge_id: uuid.UUID) -> None:
        self._edges.pop(edge_id, None)

    def list_edges(
        self,
        source_id: Optional[uuid.UUID] = None,
        target_id: Optional[uuid.UUID] = None,
        edge_type: Optional[str] = None,
    ) -> list[Edge]:
        edges = list(self._edges.values())
        if source_id is not None:
            edges = [e for e in edges if e.source_id == source_id]
        if target_id is not None:
            edges = [e for e in edges if e.target_id == target_id]
        if edge_type is not None:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_concept(name: str) -> Concept:
    return Concept(name=name, description=f"Test concept {name}", created_by="agent")


def _make_structural_edge(
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    edge_type: str,
) -> Edge:
    return Edge(
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        evidence_type="structural",
        confidence=1.0,
    )


# ---------------------------------------------------------------------------
# AC1: Three direct callers → all appear at depth 1 with confidence 1.0
# ---------------------------------------------------------------------------


class TestAC1ThreeDirectCallers:
    """AC1: function called by 3 others → 3 callers at depth=1, confidence=1.0."""

    def test_three_callers_all_appear(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        A = _make_concept("A")
        B = _make_concept("B")
        C = _make_concept("C")
        for c in [X, A, B, C]:
            store.create_concept(c)

        # A, B, C all call X (incoming edges to X)
        store.create_edge(_make_structural_edge(A.id, X.id, "calls"))
        store.create_edge(_make_structural_edge(B.id, X.id, "calls"))
        store.create_edge(_make_structural_edge(C.id, X.id, "calls"))

        result = compute_structural_impact(store, X.id)

        assert len(result) == 3
        target_ids = {e.target_concept_id for e in result}
        assert target_ids == {A.id, B.id, C.id}

    def test_all_entries_have_confidence_1_0(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        A = _make_concept("A")
        for c in [X, A]:
            store.create_concept(c)
        store.create_edge(_make_structural_edge(A.id, X.id, "calls"))

        result = compute_structural_impact(store, X.id)

        assert all(entry.confidence == 1.0 for entry in result)

    def test_all_entries_at_depth_1(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        A = _make_concept("A")
        B = _make_concept("B")
        C = _make_concept("C")
        for c in [X, A, B, C]:
            store.create_concept(c)
        store.create_edge(_make_structural_edge(A.id, X.id, "calls"))
        store.create_edge(_make_structural_edge(B.id, X.id, "calls"))
        store.create_edge(_make_structural_edge(C.id, X.id, "calls"))

        result = compute_structural_impact(store, X.id)

        assert all(entry.depth == 1 for entry in result)


# ---------------------------------------------------------------------------
# AC2: Class with 2 subclasses, each called by 1 function → 4 concepts at depth 2
# ---------------------------------------------------------------------------


class TestAC2FourConceptsAtDepthTwo:
    """AC2: BFS at max_depth=2 produces 2 depth-1 and 2 depth-2 entries."""

    def test_four_concepts_total(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")    # base class
        S1 = _make_concept("S1")  # subclass 1
        S2 = _make_concept("S2")  # subclass 2
        F1 = _make_concept("F1")  # function that depends on S1
        F2 = _make_concept("F2")  # function that depends on S2
        for c in [X, S1, S2, F1, F2]:
            store.create_concept(c)

        # S1 and S2 inherit X (incoming to X at depth 1)
        store.create_edge(_make_structural_edge(S1.id, X.id, "inherits"))
        store.create_edge(_make_structural_edge(S2.id, X.id, "inherits"))
        # F1 calls S1, F2 calls S2 (incoming to S1/S2 at depth 2)
        store.create_edge(_make_structural_edge(F1.id, S1.id, "calls"))
        store.create_edge(_make_structural_edge(F2.id, S2.id, "calls"))

        result = compute_structural_impact(store, X.id, max_depth=2)

        assert len(result) == 4

    def test_depth_1_contains_subclasses(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        S1 = _make_concept("S1")
        S2 = _make_concept("S2")
        F1 = _make_concept("F1")
        F2 = _make_concept("F2")
        for c in [X, S1, S2, F1, F2]:
            store.create_concept(c)
        store.create_edge(_make_structural_edge(S1.id, X.id, "inherits"))
        store.create_edge(_make_structural_edge(S2.id, X.id, "inherits"))
        store.create_edge(_make_structural_edge(F1.id, S1.id, "calls"))
        store.create_edge(_make_structural_edge(F2.id, S2.id, "calls"))

        result = compute_structural_impact(store, X.id, max_depth=2)

        depth1_ids = {e.target_concept_id for e in result if e.depth == 1}
        assert depth1_ids == {S1.id, S2.id}

    def test_depth_2_contains_callers_of_subclasses(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        S1 = _make_concept("S1")
        S2 = _make_concept("S2")
        F1 = _make_concept("F1")
        F2 = _make_concept("F2")
        for c in [X, S1, S2, F1, F2]:
            store.create_concept(c)
        store.create_edge(_make_structural_edge(S1.id, X.id, "inherits"))
        store.create_edge(_make_structural_edge(S2.id, X.id, "inherits"))
        store.create_edge(_make_structural_edge(F1.id, S1.id, "calls"))
        store.create_edge(_make_structural_edge(F2.id, S2.id, "calls"))

        result = compute_structural_impact(store, X.id, max_depth=2)

        depth2_ids = {e.target_concept_id for e in result if e.depth == 2}
        assert depth2_ids == {F1.id, F2.id}

    def test_max_depth_1_excludes_depth_2_concepts(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        S1 = _make_concept("S1")
        S2 = _make_concept("S2")
        F1 = _make_concept("F1")
        F2 = _make_concept("F2")
        for c in [X, S1, S2, F1, F2]:
            store.create_concept(c)
        store.create_edge(_make_structural_edge(S1.id, X.id, "inherits"))
        store.create_edge(_make_structural_edge(S2.id, X.id, "inherits"))
        store.create_edge(_make_structural_edge(F1.id, S1.id, "calls"))
        store.create_edge(_make_structural_edge(F2.id, S2.id, "calls"))

        result = compute_structural_impact(store, X.id, max_depth=1)

        # Only depth-1 entries; F1/F2 are excluded
        assert len(result) == 2
        assert all(e.depth == 1 for e in result)


# ---------------------------------------------------------------------------
# AC3: ImpactEntry includes relationship_path and rationale
# ---------------------------------------------------------------------------


class TestAC3RelationshipPathAndRationale:
    """AC3: Each ImpactEntry must carry a non-empty relationship_path and rationale."""

    def test_relationship_path_contains_edge_id(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        A = _make_concept("A")
        store.create_concept(X)
        store.create_concept(A)
        edge = _make_structural_edge(A.id, X.id, "calls")
        store.create_edge(edge)

        result = compute_structural_impact(store, X.id)

        assert len(result) == 1
        entry = result[0]
        assert len(entry.relationship_path) >= 1
        assert str(edge.id) in entry.relationship_path

    def test_rationale_is_non_empty(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        A = _make_concept("A")
        store.create_concept(X)
        store.create_concept(A)
        store.create_edge(_make_structural_edge(A.id, X.id, "imports"))

        result = compute_structural_impact(store, X.id)

        assert len(result) == 1
        assert result[0].rationale != ""

    def test_depth_2_path_has_two_edge_ids(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        S = _make_concept("S")
        F = _make_concept("F")
        for c in [X, S, F]:
            store.create_concept(c)
        e1 = _make_structural_edge(S.id, X.id, "inherits")
        e2 = _make_structural_edge(F.id, S.id, "calls")
        store.create_edge(e1)
        store.create_edge(e2)

        result = compute_structural_impact(store, X.id, max_depth=2)

        depth2_entries = [e for e in result if e.depth == 2]
        assert len(depth2_entries) == 1
        path = depth2_entries[0].relationship_path
        assert len(path) == 2
        assert str(e1.id) in path
        assert str(e2.id) in path


# ---------------------------------------------------------------------------
# AC4: No structural dependents → empty list
# ---------------------------------------------------------------------------


class TestAC4NoDependents:
    """AC4: A concept with no incoming structural edges yields an empty impact list."""

    def test_isolated_concept_returns_empty(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        store.create_concept(X)

        result = compute_structural_impact(store, X.id)

        assert result == []

    def test_outgoing_edges_do_not_count_as_impact(self) -> None:
        """Outgoing edges (X depends on Y) should not appear in X's blast radius."""
        store = _InMemoryStore()
        X = _make_concept("X")
        Y = _make_concept("Y")
        store.create_concept(X)
        store.create_concept(Y)
        # X calls Y — X depends on Y, not the other way around
        store.create_edge(_make_structural_edge(X.id, Y.id, "calls"))

        result = compute_structural_impact(store, X.id)

        assert result == []


# ---------------------------------------------------------------------------
# Extra: cycle safety and non-structural edge filtering
# ---------------------------------------------------------------------------


class TestEdgeFiltering:
    """Only structural edges should be traversed; semantic/historical edges are ignored."""

    def test_semantic_edges_not_traversed(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        A = _make_concept("A")
        store.create_concept(X)
        store.create_concept(A)
        # Semantic edge — should NOT appear in structural impact
        store.create_edge(
            Edge(
                source_id=A.id,
                target_id=X.id,
                edge_type="depends-on",
                evidence_type="semantic",
                confidence=0.8,
            )
        )

        result = compute_structural_impact(store, X.id)

        assert result == []

    def test_historical_edges_not_traversed(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        A = _make_concept("A")
        store.create_concept(X)
        store.create_concept(A)
        store.create_edge(
            Edge(
                source_id=A.id,
                target_id=X.id,
                edge_type="co-changes-with",
                evidence_type="historical",
                confidence=0.9,
            )
        )

        result = compute_structural_impact(store, X.id)

        assert result == []

    def test_all_structural_edge_types_traversed(self) -> None:
        """calls, imports, inherits, type-references are all structural."""
        store = _InMemoryStore()
        X = _make_concept("X")
        A = _make_concept("A_calls")
        B = _make_concept("B_imports")
        C = _make_concept("C_inherits")
        D = _make_concept("D_type_ref")
        for c in [X, A, B, C, D]:
            store.create_concept(c)

        store.create_edge(_make_structural_edge(A.id, X.id, "calls"))
        store.create_edge(_make_structural_edge(B.id, X.id, "imports"))
        store.create_edge(_make_structural_edge(C.id, X.id, "inherits"))
        store.create_edge(_make_structural_edge(D.id, X.id, "type-references"))

        result = compute_structural_impact(store, X.id)

        assert len(result) == 4
        target_ids = {e.target_concept_id for e in result}
        assert target_ids == {A.id, B.id, C.id, D.id}


class TestCycleSafety:
    """Cyclic graphs should not cause infinite loops."""

    def test_direct_cycle_does_not_loop(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        A = _make_concept("A")
        store.create_concept(X)
        store.create_concept(A)
        # A calls X, X calls A — creates a cycle
        store.create_edge(_make_structural_edge(A.id, X.id, "calls"))
        store.create_edge(_make_structural_edge(X.id, A.id, "calls"))

        result = compute_structural_impact(store, X.id)

        # A appears once at depth 1; X is already visited so cycle is safe
        assert len(result) == 1
        assert result[0].target_concept_id == A.id
        assert result[0].depth == 1

    def test_longer_cycle_terminates(self) -> None:
        store = _InMemoryStore()
        X = _make_concept("X")
        A = _make_concept("A")
        B = _make_concept("B")
        for c in [X, A, B]:
            store.create_concept(c)
        # A→X, B→A, X→B (cycle: X→B→A→X when reversed)
        store.create_edge(_make_structural_edge(A.id, X.id, "calls"))
        store.create_edge(_make_structural_edge(B.id, A.id, "calls"))
        store.create_edge(_make_structural_edge(X.id, B.id, "calls"))

        result = compute_structural_impact(store, X.id, max_depth=10)

        # Should not raise; each node appears at most once
        target_ids = [e.target_concept_id for e in result]
        assert len(target_ids) == len(set(target_ids))
