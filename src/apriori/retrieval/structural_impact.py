"""Structural impact computation — Story 12.2 (ERD §5.1).

Computes the blast radius of a concept by performing a BFS traversal of
incoming structural edges. A concept B has a structural dependency on A when
there is a structural edge from B to A (B calls/imports/inherits/type-references A).
If A changes, all such B are impacted.

All edges traversed must have ``evidence_type == "structural"``.
Confidence is always 1.0 because structural dependencies are deterministic.

Layer: retrieval/ (Layer 3). Reads from KnowledgeStore; never writes.
"""

from __future__ import annotations

import uuid
from collections import deque

from apriori.models.impact import ImpactEntry
from apriori.storage.protocol import KnowledgeStore


def compute_structural_impact(
    store: KnowledgeStore,
    target_concept_id: uuid.UUID,
    max_depth: int = 3,
) -> list[ImpactEntry]:
    """Return all concepts that structurally depend on *target_concept_id*.

    Performs a reverse BFS starting from *target_concept_id*: at each step,
    finds all concepts that have an incoming structural edge pointing to the
    current frontier, and enqueues them for the next depth level.

    Only edges with ``evidence_type == "structural"`` are traversed.  Semantic
    and historical edges are ignored. Each concept appears at most once in the
    result (the first BFS visit determines its depth and path).

    Args:
        store: The KnowledgeStore to query. Must support
            ``list_edges(target_id=...)``.
        target_concept_id: UUID of the concept whose blast radius to compute.
        max_depth: Maximum number of hops to follow.  Defaults to 3.
            A value of 1 returns only direct dependents.

    Returns:
        A list of :class:`~apriori.models.impact.ImpactEntry` objects, one per
        impacted concept. Entries are ordered breadth-first (depth 1 first,
        then depth 2, etc.). Returns an empty list when no structural
        dependents exist.
    """
    results: list[ImpactEntry] = []
    visited: set[uuid.UUID] = {target_concept_id}

    # Queue items: (concept_id, current_depth, path_of_edge_ids_from_root)
    queue: deque[tuple[uuid.UUID, int, list[str]]] = deque()
    queue.append((target_concept_id, 0, []))

    while queue:
        current_id, current_depth, current_path = queue.popleft()

        if current_depth >= max_depth:
            continue

        incoming_structural = [
            e
            for e in store.list_edges(target_id=current_id)
            if e.evidence_type == "structural"
        ]

        for edge in incoming_structural:
            dependent_id = edge.source_id
            if dependent_id in visited:
                continue

            visited.add(dependent_id)
            new_depth = current_depth + 1
            new_path = current_path + [str(edge.id)]

            entry = ImpactEntry(
                target_concept_id=dependent_id,
                confidence=1.0,
                relationship_path=new_path,
                depth=new_depth,
                rationale=(
                    f"Structural dependency via '{edge.edge_type}' edge "
                    f"(depth {new_depth})"
                ),
            )
            results.append(entry)
            queue.append((dependent_id, new_depth, new_path))

    return results
