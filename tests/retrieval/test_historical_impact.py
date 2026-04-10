"""Tests for historical impact computation — AC traceability: Story 12.4.

AC1: Given two files modified together in 8/10 commits, historical impact
     includes a high-confidence co-change relationship.
AC2: Given recency decay, recent co-changes contribute more than older ones.
AC3: Given computation, git history is processed in one batch scan.
AC4: Given detected co-change, `co-changes-with` edges are created/updated in store.
"""

from __future__ import annotations

import uuid
from typing import Optional

from apriori.models.concept import CodeReference, Concept
from apriori.models.edge import Edge
from apriori.retrieval.historical_impact import (
    HistoricalImpactConfig,
    build_historical_impact_pre_run_hook,
    compute_file_cochange_confidences,
    compute_historical_impact_edges,
)


class _InMemoryStore:
    """Minimal KnowledgeStore subset for historical impact tests."""

    def __init__(self) -> None:
        self._concepts: dict[uuid.UUID, Concept] = {}
        self._edges: dict[uuid.UUID, Edge] = {}

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


def _make_concept(name: str, file_path: str) -> Concept:
    return Concept(
        name=name,
        description=f"Concept for {file_path}",
        created_by="agent",
        code_references=[
            CodeReference(
                symbol=name,
                file_path=file_path,
                line_range=(1, 10),
                content_hash="a" * 64,
                semantic_anchor=f"{name}-anchor",
            )
        ],
    )


class TestAC1HighConfidenceCoChange:
    def test_two_files_cochange_8_of_10_is_high_confidence(self) -> None:
        commits = [
            {"a.py", "b.py"} for _ in range(8)
        ] + [
            {"a.py", "c.py"},
            {"a.py", "d.py"},
        ]

        confidences = compute_file_cochange_confidences(
            commits,
            HistoricalImpactConfig(decay_mode="none", max_commits=10),
        )

        confidence_ab = confidences[("a.py", "b.py")].confidence
        assert confidence_ab == 0.8
        assert confidence_ab >= 0.7


class TestAC2RecencyDecay:
    def test_recent_cochanges_outscore_older_cochanges(self) -> None:
        commits = [
            {"a.py", "recent.py"},
            {"a.py", "recent.py"},
            {"a.py", "recent.py"},
            {"a.py", "old.py"},
            {"a.py", "old.py"},
            {"a.py", "old.py"},
        ]

        confidences = compute_file_cochange_confidences(
            commits,
            HistoricalImpactConfig(
                decay_mode="exponential",
                decay_window=6,
                decay_lambda=4.0,
                max_commits=6,
                min_confidence=0.0,
            ),
        )

        recent_score = confidences[("a.py", "recent.py")].confidence
        old_score = confidences[("a.py", "old.py")].confidence
        assert recent_score > old_score


class TestAC3BatchProcessing:
    def test_git_history_scanned_once(self) -> None:
        store = _InMemoryStore()
        concept_a = _make_concept("A", "a.py")
        concept_b = _make_concept("B", "b.py")
        store.create_concept(concept_a)
        store.create_concept(concept_b)

        calls: list[int] = []

        def _history_reader(_repo_path, _max_commits):
            calls.append(1)
            return [
                {"a.py", "b.py"},
                {"a.py", "b.py"},
            ]

        compute_historical_impact_edges(
            store,
            repo_path="/tmp/repo",
            config=HistoricalImpactConfig(decay_mode="none", max_commits=50),
            read_git_history=_history_reader,
        )

        assert calls == [1]


class TestAC4StoreEdges:
    def test_cochanges_with_edges_created_or_updated_with_computed_confidence(self) -> None:
        store = _InMemoryStore()
        concept_a = _make_concept("A", "a.py")
        concept_b = _make_concept("B", "b.py")
        store.create_concept(concept_a)
        store.create_concept(concept_b)

        existing = Edge(
            source_id=concept_a.id,
            target_id=concept_b.id,
            edge_type="co-changes-with",
            evidence_type="historical",
            confidence=0.1,
        )
        store.create_edge(existing)

        def _history_reader(_repo_path, _max_commits):
            return [
                {"a.py", "b.py"},
                {"a.py", "b.py"},
                {"a.py", "c.py"},
                {"a.py", "d.py"},
            ]

        compute_historical_impact_edges(
            store,
            repo_path="/tmp/repo",
            config=HistoricalImpactConfig(decay_mode="none", max_commits=10),
            read_git_history=_history_reader,
        )

        edges = store.list_edges(
            source_id=concept_a.id,
            target_id=concept_b.id,
            edge_type="co-changes-with",
        )
        assert len(edges) == 1
        assert edges[0].confidence == 0.5


class TestPreRunHookRegistration:
    def test_pre_run_hook_executes_historical_impact_computation(self) -> None:
        store = _InMemoryStore()
        concept_a = _make_concept("A", "a.py")
        concept_b = _make_concept("B", "b.py")
        store.create_concept(concept_a)
        store.create_concept(concept_b)

        def _history_reader(_repo_path, _max_commits):
            return [{"a.py", "b.py"}]

        hook = build_historical_impact_pre_run_hook(
            store,
            repo_path="/tmp/repo",
            config=HistoricalImpactConfig(decay_mode="none", max_commits=5),
            read_git_history=_history_reader,
        )

        hook()

        edges = store.list_edges(edge_type="co-changes-with")
        assert len(edges) == 2  # A->B and B->A
