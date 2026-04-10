"""KnowledgeStore Protocol — the single storage interface for A-Priori (ERD §3.2.1).

All downstream modules code against this Protocol. Concrete implementations
(SQLiteStore, DualWriter, InMemoryStore) must satisfy it structurally.
No module outside of ``apriori.storage`` may issue raw SQL or direct file I/O;
all data access flows through a KnowledgeStore instance (arch:no-raw-sql).

Usage::

    from apriori.storage.protocol import KnowledgeStore

    def compute_impact(store: KnowledgeStore, concept_id: uuid.UUID) -> None:
        concept = store.get_concept(concept_id)
        neighbors = store.get_neighbors(concept_id)
        ...

All methods are synchronous (arch:sync-first). Async optimisation is deferred
to a later phase.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional, Protocol, runtime_checkable

from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.models.librarian_activity import LibrarianActivity
from apriori.models.review_outcome import ReviewOutcome
from apriori.models.work_item import FailureRecord, WorkItem


@runtime_checkable
class KnowledgeStore(Protocol):
    """Structural protocol for all A-Priori storage backends (ERD §3.2.1).

    Implementations include SQLiteStore (primary), DualWriter (production
    coordinator), and InMemoryStore (tests/prototyping). All three must satisfy
    this protocol identically — callers never depend on a concrete class.

    **Error contract (applies to all methods unless stated otherwise):**

    - ``get_*`` methods return ``None`` when the requested entity does not exist.
    - ``update_*`` and ``delete_*`` methods raise ``KeyError`` if the entity is
      not found.
    - ``create_*`` methods raise ``ValueError`` if a uniqueness constraint would
      be violated (e.g. duplicate ``(source_id, target_id, edge_type)`` on an
      Edge).
    - Search and list methods always return a (possibly empty) list; they never
      raise for "not found".
    """

    # -------------------------------------------------------------------------
    # Concept CRUD
    # -------------------------------------------------------------------------

    def create_concept(self, concept: Concept) -> Concept:
        """Persist a new Concept and return it.

        Args:
            concept: A fully populated Concept instance. ``concept.id`` must
                not already exist in the store.

        Returns:
            The persisted Concept (identical to the argument, post any
            implementation-side enrichment such as timestamps).

        Raises:
            ValueError: If a Concept with ``concept.id`` already exists.

        Side effects:
            Writes to the primary store. If the implementation is a DualWriter,
            also writes to the YAML flat-file store.
        """
        ...

    def get_concept(self, concept_id: uuid.UUID) -> Optional[Concept]:
        """Retrieve a Concept by its UUID.

        Args:
            concept_id: The UUID of the Concept to retrieve.

        Returns:
            The Concept if found, otherwise ``None``.
        """
        ...

    def update_concept(self, concept: Concept) -> Concept:
        """Replace an existing Concept with the supplied instance and return it.

        The caller is responsible for setting ``concept.updated_at`` before
        calling this method.

        Args:
            concept: The updated Concept. ``concept.id`` must already exist.

        Returns:
            The updated Concept as stored.

        Raises:
            KeyError: If no Concept with ``concept.id`` exists.

        Side effects:
            Overwrites the stored Concept. DualWriter implementations also
            update the YAML record.
        """
        ...

    def delete_concept(self, concept_id: uuid.UUID) -> None:
        """Remove a Concept and all its dependent Edges from the store.

        Edges whose ``source_id`` or ``target_id`` equals ``concept_id`` are
        deleted as a cascade (storage layer responsibility).

        Args:
            concept_id: The UUID of the Concept to delete.

        Raises:
            KeyError: If no Concept with ``concept_id`` exists.

        Side effects:
            Removes the Concept and any dependent Edges. DualWriter
            implementations also remove the corresponding YAML record.
        """
        ...

    def list_concepts(self, labels: Optional[set[str]] = None) -> list[Concept]:
        """Return all stored Concepts, optionally filtered by label intersection.

        Args:
            labels: When provided, return only Concepts whose ``labels`` set
                has a non-empty intersection with this set. When ``None``,
                return all Concepts.

        Returns:
            A list of matching Concepts. Order is implementation-defined.
            Returns an empty list when no Concepts match.
        """
        ...

    # -------------------------------------------------------------------------
    # Edge CRUD
    # -------------------------------------------------------------------------

    def create_edge(self, edge: Edge) -> Edge:
        """Persist a new Edge and return it.

        The ``(source_id, target_id, edge_type)`` triple must be unique within
        the store.

        Args:
            edge: A fully populated Edge instance.

        Returns:
            The persisted Edge.

        Raises:
            ValueError: If an Edge with the same ``(source_id, target_id,
                edge_type)`` triple already exists.
            KeyError: If ``source_id`` or ``target_id`` does not refer to an
                existing Concept.

        Side effects:
            Writes to the primary store. DualWriter implementations also write
            to the YAML flat-file store.
        """
        ...

    def get_edge(self, edge_id: uuid.UUID) -> Optional[Edge]:
        """Retrieve an Edge by its UUID.

        Args:
            edge_id: The UUID of the Edge to retrieve.

        Returns:
            The Edge if found, otherwise ``None``.
        """
        ...

    def update_edge(self, edge: Edge) -> Edge:
        """Replace an existing Edge and return it.

        Args:
            edge: The updated Edge. ``edge.id`` must already exist.

        Returns:
            The updated Edge as stored.

        Raises:
            KeyError: If no Edge with ``edge.id`` exists.
        """
        ...

    def delete_edge(self, edge_id: uuid.UUID) -> None:
        """Remove an Edge from the store.

        Args:
            edge_id: The UUID of the Edge to delete.

        Raises:
            KeyError: If no Edge with ``edge_id`` exists.
        """
        ...

    def list_edges(
        self,
        source_id: Optional[uuid.UUID] = None,
        target_id: Optional[uuid.UUID] = None,
        edge_type: Optional[str] = None,
    ) -> list[Edge]:
        """Return all Edges matching the supplied filters.

        All parameters are optional and combine with AND semantics.

        Args:
            source_id: When provided, include only Edges with this source.
            target_id: When provided, include only Edges with this target.
            edge_type: When provided, include only Edges of this type.

        Returns:
            A list of matching Edges. Returns an empty list when none match.
        """
        ...

    # -------------------------------------------------------------------------
    # Work Item operations
    # -------------------------------------------------------------------------

    def create_work_item(self, work_item: WorkItem) -> WorkItem:
        """Persist a new WorkItem and return it.

        WorkItems are SQLite-only; they are not dual-written to YAML.

        Args:
            work_item: A fully populated WorkItem instance.

        Returns:
            The persisted WorkItem.

        Raises:
            ValueError: If a WorkItem with ``work_item.id`` already exists.
        """
        ...

    def get_work_item(self, work_item_id: uuid.UUID) -> Optional[WorkItem]:
        """Retrieve a WorkItem by its UUID.

        Args:
            work_item_id: The UUID of the WorkItem to retrieve.

        Returns:
            The WorkItem if found, otherwise ``None``.
        """
        ...

    def update_work_item(self, work_item: WorkItem) -> WorkItem:
        """Replace an existing WorkItem and return it.

        Args:
            work_item: The updated WorkItem. ``work_item.id`` must already exist.

        Returns:
            The updated WorkItem as stored.

        Raises:
            KeyError: If no WorkItem with ``work_item.id`` exists.
        """
        ...

    def resolve_work_item(self, work_item_id: uuid.UUID) -> WorkItem:
        """Mark a WorkItem as resolved and return it.

        Sets ``resolved=True`` and ``resolved_at`` to the current UTC time.

        Args:
            work_item_id: The UUID of the WorkItem to resolve.

        Returns:
            The updated WorkItem with ``resolved=True``.

        Raises:
            KeyError: If no WorkItem with ``work_item_id`` exists.
        """
        ...

    def get_pending_work_items(self) -> list[WorkItem]:
        """Return all WorkItems that are not yet resolved.

        Returns:
            A list of WorkItems where ``resolved=False``. Order is
            implementation-defined (callers should sort by priority themselves).
        """
        ...

    def list_work_items(self, limit: int = 20) -> list[WorkItem]:
        """Return the most recent WorkItems ordered by ``created_at`` descending.

        Used by the activity feed in the UI to display the most recent librarian
        iterations regardless of resolution status.

        Args:
            limit: Maximum number of items to return. Defaults to 20.

        Returns:
            Up to ``limit`` WorkItems ordered by ``created_at`` descending (newest
            first). Returns an empty list when no WorkItems exist.
        """
        ...

    def record_failure(
        self, work_item_id: uuid.UUID, record: FailureRecord
    ) -> WorkItem:
        """Append a FailureRecord to a WorkItem and increment its failure count.

        Called by the librarian loop each time an iteration fails for the given
        work item (arch:librarian-loop).

        Args:
            work_item_id: The UUID of the WorkItem that failed.
            record: A FailureRecord capturing diagnostic context for this
                failure (model used, prompt template, reason, optional scores,
                optional reviewer feedback).

        Returns:
            The updated WorkItem with the new FailureRecord appended and
            ``failure_count`` incremented by one.

        Raises:
            KeyError: If no WorkItem with ``work_item_id`` exists.
        """
        ...

    def escalate_work_item(self, work_item_id: uuid.UUID) -> WorkItem:
        """Mark a WorkItem as escalated for human review and return it.

        Sets ``escalated=True``. The item remains in the pending queue until
        explicitly resolved.

        Args:
            work_item_id: The UUID of the WorkItem to escalate.

        Returns:
            The updated WorkItem with ``escalated=True``.

        Raises:
            KeyError: If no WorkItem with ``work_item_id`` exists.
        """
        ...

    def get_escalated_items(self) -> list[WorkItem]:
        """Return all WorkItems that have been escalated.

        Returns:
            A list of WorkItems where ``escalated=True``. Includes both
            resolved and unresolved escalated items.
        """
        ...

    def get_work_item_stats(self) -> dict[str, int]:
        """Return aggregate counts for work items grouped by state.

        Returns:
            A dict with integer counts for the following keys:
            - ``total``: all work items
            - ``pending``: unresolved work items (``resolved=False``)
            - ``resolved``: resolved work items (``resolved=True``)
            - ``escalated``: escalated work items (``escalated=True``)
        """
        ...

    def delete_old_work_items(self, days: int) -> int:
        """Delete resolved WorkItems whose resolved_at is older than ``days`` days.

        Only resolved items are eligible for deletion. Unresolved items are
        never deleted by this method regardless of age.

        Args:
            days: Retention period in days. Items with ``resolved_at`` older
                than ``days`` days ago are permanently deleted.

        Returns:
            The number of work items deleted.
        """
        ...

    # -------------------------------------------------------------------------
    # Review Outcome operations
    # -------------------------------------------------------------------------

    def create_review_outcome(self, outcome: ReviewOutcome) -> ReviewOutcome:
        """Persist a ReviewOutcome from the Level 2 audit UI and return it.

        Args:
            outcome: A fully populated ReviewOutcome instance.

        Returns:
            The persisted ReviewOutcome.

        Side effects:
            Writes to the primary store. DualWriter implementations also write
            to the YAML record for the associated Concept.
        """
        ...

    def get_review_outcomes_for_concept(
        self, concept_id: uuid.UUID
    ) -> list[ReviewOutcome]:
        """Return all ReviewOutcomes associated with a specific Concept.

        Args:
            concept_id: The UUID of the Concept whose review history to fetch.

        Returns:
            A list of ReviewOutcomes ordered by ``created_at`` ascending.
            Returns an empty list if no outcomes exist for this Concept.
        """
        ...

    def list_review_outcomes(self) -> list[ReviewOutcome]:
        """Return all ReviewOutcomes in the store.

        Returns:
            A list of all ReviewOutcomes. Order is implementation-defined.
        """
        ...

    # -------------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------------

    def search_semantic(
        self, query_embedding: list[float], limit: int = 10
    ) -> list[Concept]:
        """Find Concepts whose embeddings are nearest to the query embedding.

        Uses the sqlite-vec vector index under the hood (arch:sqlite-vec-storage).
        Embedding model is all-MiniLM-L6-v2 (384 dimensions, arch:embedding-model).

        Args:
            query_embedding: A 384-dimensional float vector representing the
                query. Must be the same embedding space used to index Concepts.
            limit: Maximum number of results to return. Defaults to 10.

        Returns:
            Up to ``limit`` Concepts ordered by cosine similarity descending.
        """
        ...

    def search_keyword(self, query: str, limit: int = 10) -> list[Concept]:
        """Find Concepts whose name or description contains the query string.

        Args:
            query: The substring to search for (case-insensitive).
            limit: Maximum number of results to return. Defaults to 10.

        Returns:
            Up to ``limit`` matching Concepts. Order is implementation-defined.
        """
        ...

    def search_by_file(self, file_path: str) -> list[Concept]:
        """Return all Concepts that have a CodeReference anchored to a file.

        Args:
            file_path: The file path to match against
                ``Concept.code_references[*].file_path`` (exact match).

        Returns:
            All Concepts with at least one CodeReference whose ``file_path``
            equals the given argument.
        """
        ...

    # -------------------------------------------------------------------------
    # Graph traversal
    # -------------------------------------------------------------------------

    def get_neighbors(
        self,
        concept_id: uuid.UUID,
        edge_type: Optional[str] = None,
        direction: str = "both",
    ) -> list[Concept]:
        """Return Concepts directly connected to the given Concept via Edges.

        Args:
            concept_id: The UUID of the hub Concept.
            edge_type: When provided, consider only Edges of this type.
            direction: ``"outgoing"`` returns targets of edges from the hub;
                ``"incoming"`` returns sources of edges pointing at the hub;
                ``"both"`` (default) returns both sets.

        Returns:
            A deduplicated list of neighboring Concepts.

        Raises:
            ValueError: If ``direction`` is not one of ``"outgoing"``,
                ``"incoming"``, or ``"both"``.
        """
        ...

    def traverse_graph(
        self, start_id: uuid.UUID, max_depth: int = 3
    ) -> list[Concept]:
        """Breadth-first traversal of the graph starting from a Concept.

        Follows outgoing Edges and collects all reachable Concepts up to
        ``max_depth`` hops from ``start_id``.

        Args:
            start_id: The UUID of the starting Concept. It is included in the
                result if it exists.
            max_depth: Maximum number of edge hops to follow. Defaults to 3.

        Returns:
            A list of all reachable Concepts (including the start Concept)
            within ``max_depth`` hops, in breadth-first order. Each Concept
            appears at most once.
        """
        ...

    # -------------------------------------------------------------------------
    # Metrics
    # -------------------------------------------------------------------------

    def get_metrics(self) -> dict[str, Any]:
        """Return aggregate statistics about the current store state.

        Implementations must include at minimum:
        - ``concept_count`` (int): total number of Concepts
        - ``edge_count`` (int): total number of Edges
        - ``work_item_count`` (int): total number of WorkItems
        - ``review_outcome_count`` (int): total number of ReviewOutcomes

        Implementations may include additional keys (e.g. embedding index size,
        pending work item count, escalated item count).

        Returns:
            A dict of metric names to values. Keys listed above are guaranteed
            to be present.
        """
        ...

    def count_covered_files(self) -> int:
        """Count the number of distinct source file paths referenced by at
        least one Concept's ``code_references``.

        Used by MetricsEngine to compute coverage: the caller divides this
        count by the known total number of source files in the repository.

        Returns:
            Number of distinct ``file_path`` values across all CodeReferences
            stored in the concepts table.  Returns 0 when no Concepts have
            CodeReferences.
        """
        ...

    def count_fresh_active_concepts(self, active_days: int = 30) -> tuple[int, int]:
        """Return (fresh_count, active_count) for freshness metric computation.

        - *active* concept: one whose ``updated_at`` falls within the last
          ``active_days`` days.
        - *fresh* concept: an active concept whose ``last_verified`` is not
          ``None`` and is more recent than its ``updated_at``.

        Args:
            active_days: Lookback window in days for "actively developed".
                Defaults to 30.

        Returns:
            A ``(fresh_count, active_count)`` tuple.  ``fresh_count`` ≤
            ``active_count``.  Both are 0 when no Concepts exist.
        """
        ...

    def count_blast_radius_complete(self) -> tuple[int, int]:
        """Return (with_profile_count, total_count) for blast-radius completeness.

        A Concept is considered to have a *complete* blast-radius profile when
        its ``impact_profile`` column is not ``NULL``.

        Returns:
            A ``(with_profile_count, total_count)`` tuple.  Both are 0 when
            no Concepts exist.
        """
        ...

    # -------------------------------------------------------------------------
    # Embedding operations
    # -------------------------------------------------------------------------

    def store_embedding(self, concept_id: uuid.UUID, vector: list[float]) -> None:
        """Persist a pre-computed embedding vector for a Concept.

        Replaces any existing embedding for the concept. This is the protocol
        entry point for batch embedding writes — callers must never issue raw
        SQL directly (arch:no-raw-sql).

        Args:
            concept_id: The UUID of the Concept whose embedding to store.
            vector: A list of floats representing the embedding. Length must
                match the model's output dimensions (768 for e5-base-v2).

        Side effects:
            Writes to the sqlite-vec ``concept_embeddings`` table only.
            Embeddings are never dual-written to YAML.
        """
        ...

    # -------------------------------------------------------------------------
    # Bulk operations
    # -------------------------------------------------------------------------

    def rebuild_index(self) -> None:
        """Rebuild the vector similarity index from all stored Concept embeddings.

        Should be called after bulk imports or schema migrations that invalidate
        the index. This is a potentially long-running operation.

        Side effects:
            Drops and rebuilds the sqlite-vec index. The store remains readable
            during the rebuild in implementations that support it, but search
            results may be stale until the operation completes.
        """
        ...

    # -------------------------------------------------------------------------
    # Librarian Activity operations
    # -------------------------------------------------------------------------

    def create_librarian_activity(self, activity: LibrarianActivity) -> LibrarianActivity:
        """Persist a LibrarianActivity record for one loop iteration.

        SQLite-only — activity records are never dual-written to YAML.

        Args:
            activity: A fully populated LibrarianActivity instance.

        Returns:
            The persisted LibrarianActivity (identical to the argument).

        Raises:
            ValueError: If an activity with ``activity.id`` already exists.
        """
        ...

    def list_librarian_activities(
        self, run_id: Optional[uuid.UUID] = None
    ) -> list[LibrarianActivity]:
        """Return all LibrarianActivity records, optionally filtered by run_id.

        Args:
            run_id: When provided, return only records from this run.

        Returns:
            A list of LibrarianActivity records ordered by ``iteration`` ascending.
        """
        ...
