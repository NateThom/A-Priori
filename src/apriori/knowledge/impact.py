"""Impact computation services for blast radius profiles (Story 12.3).

Layer 2 (knowledge/) — may import from models/, storage/, config.py.
No imports from structural/, semantic/, retrieval/ (arch:layer-flow).
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Iterable

from apriori.models.edge import Edge
from apriori.models.impact import ImpactEntry, ImpactProfile
from apriori.storage.protocol import KnowledgeStore


# Semantic edge types used for blast-radius traversal in Story 12.3.
# Explicitly excludes "relates-to" and "owned-by" per acceptance criteria.
_TRAVERSABLE_SEMANTIC_EDGE_TYPES: frozenset[str] = frozenset(
    {
        "depends-on",
        "implements",
        "shares-assumption-about",
        "extends",
        "supersedes",
    }
)


class ImpactComputer:
    """Computes semantic impact entries and assembles an ImpactProfile."""

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    def compute_semantic_impact(
        self,
        concept_id: uuid.UUID,
        *,
        max_depth: int = 3,
    ) -> list[ImpactEntry]:
        """Return semantic blast-radius entries via BFS over outgoing edges."""
        if max_depth < 1:
            return []

        visited: set[uuid.UUID] = {concept_id}
        impact: list[ImpactEntry] = []
        queue: deque[tuple[uuid.UUID, float, list[str], list[str], int]] = deque(
            [(concept_id, 1.0, [], [], 0)]
        )

        while queue:
            current_id, current_confidence, path_ids, path_types, depth = queue.popleft()
            if depth >= max_depth:
                continue

            for edge in self._semantic_outgoing_edges(current_id):
                target_id = edge.target_id
                if target_id in visited:
                    continue

                next_depth = depth + 1
                next_confidence = current_confidence * edge.confidence
                next_path_ids = [*path_ids, str(edge.id)]
                next_path_types = [*path_types, edge.edge_type]

                visited.add(target_id)
                impact.append(
                    ImpactEntry(
                        target_concept_id=target_id,
                        confidence=next_confidence,
                        relationship_path=next_path_ids,
                        depth=next_depth,
                        rationale=self._rationale_for_path(next_path_types),
                    )
                )
                queue.append(
                    (target_id, next_confidence, next_path_ids, next_path_types, next_depth)
                )

        return impact

    def compute_profile(
        self,
        concept_id: uuid.UUID,
        *,
        structural_impact: Iterable[ImpactEntry] | None = None,
        historical_impact: Iterable[ImpactEntry] | None = None,
    ) -> ImpactProfile:
        """Compute and return an ImpactProfile with semantic impact populated."""
        semantic_impact = self.compute_semantic_impact(concept_id)
        return ImpactProfile(
            structural_impact=list(structural_impact or []),
            semantic_impact=semantic_impact,
            historical_impact=list(historical_impact or []),
            structural_only=len(semantic_impact) == 0,
            last_computed=datetime.now(timezone.utc),
        )

    def _semantic_outgoing_edges(self, concept_id: uuid.UUID) -> list[Edge]:
        return [
            edge
            for edge in self._store.list_edges(source_id=concept_id)
            if edge.evidence_type == "semantic"
            and edge.edge_type in _TRAVERSABLE_SEMANTIC_EDGE_TYPES
        ]

    @staticmethod
    def _rationale_for_path(path_types: list[str]) -> str:
        if len(path_types) == 1:
            return f"Semantic coupling via {path_types[0]}."
        return "Semantic coupling path: " + " -> ".join(path_types) + "."
