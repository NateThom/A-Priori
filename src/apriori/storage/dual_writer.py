"""DualWriter — KnowledgeStore implementation that coordinates SQLite + YAML writes.

Implements the KnowledgeStore protocol by composing a SQLiteStore (acceleration
layer) and a YamlStore (authoritative flat-file store). Write order is always
YAML first (authoritative), then SQLite. SQLite failures are logged as warnings
and do not propagate. YAML failures propagate.

WorkItems and ReviewOutcomes are SQLite-only and are never written to YAML.
All reads are delegated to SQLite.

Architecture notes (arch:sqlite-vec-storage, arch:no-raw-sql):
- This module is the production coordinator — no raw SQL here.
- The YAML store is the source of truth for human-readable backup/export.
- SQLite is the runtime acceleration layer (vector search, FTS, FK integrity).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.models.review_outcome import ReviewOutcome
from apriori.models.work_item import FailureRecord, WorkItem
from apriori.storage.sqlite_store import SQLiteStore
from apriori.storage.yaml_store import YamlStore

logger = logging.getLogger(__name__)


class DualWriter:
    """Coordinates writes to both SQLite and YAML stores (ERD §3.2.4).

    YAML is written first (authoritative). SQLite is written second
    (acceleration layer). SQLite write failures are tolerated: a warning is
    logged and the method returns normally. YAML failures propagate.

    Reads are always served from SQLite for performance.

    Args:
        sqlite_store: The SQLite backend (primary runtime store).
        yaml_store: The YAML backend (authoritative flat-file store).
    """

    def __init__(self, sqlite_store: SQLiteStore, yaml_store: YamlStore) -> None:
        self._sqlite = sqlite_store
        self._yaml = yaml_store

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _try_sqlite(self, operation_name: str, fn, *args, **kwargs):
        """Execute a SQLite write, logging a warning on failure instead of raising."""
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.warning(
                "SQLite write failed for %s (YAML write succeeded): %s",
                operation_name,
                exc,
            )
            return None

    # -------------------------------------------------------------------------
    # Concept CRUD
    # -------------------------------------------------------------------------

    def create_concept(self, concept: Concept) -> Concept:
        """Write concept to YAML (authoritative), then SQLite (acceleration).

        If SQLite write fails, the YAML write is preserved, a warning is logged,
        and the method returns normally.

        Raises:
            ValueError: If the concept already exists (checked by YAML slug collision
                or when both stores raise).
        """
        # Check for duplicate in SQLite first (fast)
        existing = self._sqlite.get_concept(concept.id)
        if existing is not None:
            raise ValueError(f"Concept {concept.id} already exists")

        # YAML first (authoritative)
        self._yaml.write_concept(concept)

        # SQLite second (acceleration) — tolerate failure
        self._try_sqlite("create_concept", self._sqlite.create_concept, concept)

        return concept

    def get_concept(self, concept_id: uuid.UUID) -> Optional[Concept]:
        """Read from SQLite (AC6)."""
        return self._sqlite.get_concept(concept_id)

    def update_concept(self, concept: Concept) -> Concept:
        """Update concept in YAML (authoritative), then SQLite (acceleration).

        Raises:
            KeyError: If no concept with this id exists.
        """
        # Validate existence before writing (fail fast)
        existing = self._sqlite.get_concept(concept.id)
        if existing is None:
            raise KeyError(f"Concept {concept.id} not found")

        # YAML first
        self._yaml.write_concept(concept)

        # SQLite second — tolerate failure
        self._try_sqlite("update_concept", self._sqlite.update_concept, concept)

        return concept

    def delete_concept(self, concept_id: uuid.UUID) -> None:
        """Delete concept from YAML (authoritative), then SQLite (acceleration).

        Raises:
            KeyError: If no concept with this id exists.
        """
        existing = self._sqlite.get_concept(concept_id)
        if existing is None:
            raise KeyError(f"Concept {concept_id} not found")

        # YAML first
        try:
            self._yaml.delete_concept(concept_id)
        except KeyError:
            pass  # YAML may not have it if it was written without YAML

        # SQLite second — tolerate failure
        self._try_sqlite("delete_concept", self._sqlite.delete_concept, concept_id)

    def list_concepts(self, labels: Optional[set[str]] = None) -> list[Concept]:
        """Read from SQLite (AC6)."""
        return self._sqlite.list_concepts(labels)

    # -------------------------------------------------------------------------
    # Edge CRUD
    # -------------------------------------------------------------------------

    def create_edge(self, edge: Edge) -> Edge:
        """Write edge to YAML (authoritative), then SQLite (acceleration).

        SQLite failure is tolerated — YAML is preserved.

        Raises:
            ValueError: If an edge with the same (source, target, type) exists.
            KeyError: If source_id or target_id do not refer to existing Concepts.
        """
        # YAML first (authoritative)
        self._yaml.write_edge(edge)

        # SQLite second — tolerate failure
        self._try_sqlite("create_edge", self._sqlite.create_edge, edge)

        return edge

    def get_edge(self, edge_id: uuid.UUID) -> Optional[Edge]:
        """Read from SQLite (AC6)."""
        return self._sqlite.get_edge(edge_id)

    def update_edge(self, edge: Edge) -> Edge:
        """Update edge in YAML (authoritative), then SQLite (acceleration).

        Raises:
            KeyError: If no edge with this id exists.
        """
        existing = self._sqlite.get_edge(edge.id)
        if existing is None:
            raise KeyError(f"Edge {edge.id} not found")

        # YAML first
        self._yaml.write_edge(edge)

        # SQLite second — tolerate failure
        self._try_sqlite("update_edge", self._sqlite.update_edge, edge)

        return edge

    def delete_edge(self, edge_id: uuid.UUID) -> None:
        """Delete edge from both stores.

        Raises:
            KeyError: If no edge with this id exists.
        """
        existing = self._sqlite.get_edge(edge_id)
        if existing is None:
            raise KeyError(f"Edge {edge_id} not found")

        # YAML first
        try:
            self._yaml.delete_edge(edge_id)
        except KeyError:
            pass

        # SQLite second — tolerate failure
        self._try_sqlite("delete_edge", self._sqlite.delete_edge, edge_id)

    def list_edges(
        self,
        source_id: Optional[uuid.UUID] = None,
        target_id: Optional[uuid.UUID] = None,
        edge_type: Optional[str] = None,
    ) -> list[Edge]:
        """Read from SQLite (AC6)."""
        return self._sqlite.list_edges(source_id=source_id, target_id=target_id, edge_type=edge_type)

    # -------------------------------------------------------------------------
    # Work Item operations — SQLite-only (AC4)
    # -------------------------------------------------------------------------

    def create_work_item(self, work_item: WorkItem) -> WorkItem:
        """SQLite-only — WorkItems are never written to YAML (arch:sqlite-vec-storage)."""
        return self._sqlite.create_work_item(work_item)

    def get_work_item(self, work_item_id: uuid.UUID) -> Optional[WorkItem]:
        return self._sqlite.get_work_item(work_item_id)

    def update_work_item(self, work_item: WorkItem) -> WorkItem:
        return self._sqlite.update_work_item(work_item)

    def resolve_work_item(self, work_item_id: uuid.UUID) -> WorkItem:
        return self._sqlite.resolve_work_item(work_item_id)

    def get_pending_work_items(self) -> list[WorkItem]:
        return self._sqlite.get_pending_work_items()

    def list_work_items(self, limit: int = 20) -> list[WorkItem]:
        return self._sqlite.list_work_items(limit=limit)

    def record_failure(self, work_item_id: uuid.UUID, record: FailureRecord) -> WorkItem:
        return self._sqlite.record_failure(work_item_id, record)

    def escalate_work_item(self, work_item_id: uuid.UUID) -> WorkItem:
        return self._sqlite.escalate_work_item(work_item_id)

    def get_escalated_items(self) -> list[WorkItem]:
        return self._sqlite.get_escalated_items()

    def get_work_item_stats(self) -> dict[str, int]:
        return self._sqlite.get_work_item_stats()

    def delete_old_work_items(self, days: int) -> int:
        return self._sqlite.delete_old_work_items(days)

    # -------------------------------------------------------------------------
    # Review Outcome operations — SQLite-only (AC5)
    # -------------------------------------------------------------------------

    def create_review_outcome(self, outcome: ReviewOutcome) -> ReviewOutcome:
        """SQLite-only — ReviewOutcomes are never written to YAML."""
        return self._sqlite.create_review_outcome(outcome)

    def get_review_outcomes_for_concept(self, concept_id: uuid.UUID) -> list[ReviewOutcome]:
        return self._sqlite.get_review_outcomes_for_concept(concept_id)

    def list_review_outcomes(self) -> list[ReviewOutcome]:
        return self._sqlite.list_review_outcomes()

    # -------------------------------------------------------------------------
    # Search — SQLite-only (AC6)
    # -------------------------------------------------------------------------

    def search_semantic(self, query_embedding: list[float], limit: int = 10) -> list[Concept]:
        return self._sqlite.search_semantic(query_embedding, limit)

    def search_keyword(self, query: str, limit: int = 10) -> list[Concept]:
        return self._sqlite.search_keyword(query, limit)

    def search_by_file(self, file_path: str) -> list[Concept]:
        return self._sqlite.search_by_file(file_path)

    # -------------------------------------------------------------------------
    # Graph traversal — SQLite-only (AC6)
    # -------------------------------------------------------------------------

    def get_neighbors(
        self,
        concept_id: uuid.UUID,
        edge_type: Optional[str] = None,
        direction: str = "both",
    ) -> list[Concept]:
        return self._sqlite.get_neighbors(concept_id, edge_type=edge_type, direction=direction)

    def traverse_graph(self, start_id: uuid.UUID, max_depth: int = 3) -> list[Concept]:
        return self._sqlite.traverse_graph(start_id, max_depth)

    # -------------------------------------------------------------------------
    # Metrics — SQLite-only
    # -------------------------------------------------------------------------

    def get_metrics(self) -> dict[str, Any]:
        return self._sqlite.get_metrics()

    def count_covered_files(self) -> int:
        return self._sqlite.count_covered_files()

    def count_fresh_active_concepts(self, active_days: int = 30) -> tuple[int, int]:
        return self._sqlite.count_fresh_active_concepts(active_days)

    def count_blast_radius_complete(self) -> tuple[int, int]:
        return self._sqlite.count_blast_radius_complete()

    # -------------------------------------------------------------------------
    # Bulk operations
    # -------------------------------------------------------------------------

    def rebuild_index(self) -> None:
        """Rebuild the vector similarity index in SQLite."""
        self._sqlite.rebuild_index()
