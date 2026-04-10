"""Tests for KnowledgeStore protocol — AC traceability: Story 2.2.

AC:
- Given the protocol definition, when a developer reads it, then every method
  has a clear docstring specifying parameters, return type, error behavior,
  and any side effects.
- Given the protocol, when checked for completeness against ERD §3.2.1,
  then it includes all operation categories: Concept CRUD, Edge CRUD,
  Work Item operations (including record_failure, escalate_work_item,
  get_escalated_items), Review Outcome operations, Search (semantic, keyword,
  by-file), Graph traversal, Metrics, and Bulk operations (rebuild_index).
- Given the protocol, when inspected, then all methods are synchronous def.
- Given the protocol, when a write method is called, then it returns the
  created/updated entity.
"""

import inspect
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from apriori.models.concept import Concept, CodeReference
from apriori.models.edge import Edge
from apriori.models.librarian_activity import LibrarianActivity
from apriori.models.work_item import WorkItem, FailureRecord
from apriori.models.review_outcome import ReviewOutcome
from apriori.storage.protocol import KnowledgeStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_concept() -> Concept:
    return Concept(name="test_concept", description="A test concept.", created_by="agent")


def _make_edge(source_id: uuid.UUID, target_id: uuid.UUID) -> Edge:
    return Edge(
        source_id=source_id,
        target_id=target_id,
        edge_type="depends-on",
        evidence_type="semantic",
    )


def _make_work_item(concept_id: uuid.UUID) -> WorkItem:
    return WorkItem(
        item_type="verify_concept",
        concept_id=concept_id,
        description="Verify this concept is accurate.",
    )


def _make_failure_record() -> FailureRecord:
    return FailureRecord(
        attempted_at=datetime.now(timezone.utc),
        model_used="claude-3",
        prompt_template="verify_concept_v1",
        failure_reason="Ambiguous description.",
    )


def _make_review_outcome(concept_id: uuid.UUID) -> ReviewOutcome:
    return ReviewOutcome(
        concept_id=concept_id,
        reviewer="alice",
        action="verified",
    )


# ---------------------------------------------------------------------------
# Minimal concrete implementation for structural subtyping checks
# ---------------------------------------------------------------------------

class _InMemoryStore:
    """Minimal in-memory KnowledgeStore implementation for protocol tests.

    Not production code — exists solely to verify the Protocol contract.
    """

    def __init__(self) -> None:
        self._concepts: dict[uuid.UUID, Concept] = {}
        self._edges: dict[uuid.UUID, Edge] = {}
        self._work_items: dict[uuid.UUID, WorkItem] = {}
        self._review_outcomes: list[ReviewOutcome] = []
        self._activities: list[LibrarianActivity] = []

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
        if source_id:
            edges = [e for e in edges if e.source_id == source_id]
        if target_id:
            edges = [e for e in edges if e.target_id == target_id]
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges

    # --- Work Item operations ---

    def create_work_item(self, work_item: WorkItem) -> WorkItem:
        self._work_items[work_item.id] = work_item
        return work_item

    def get_work_item(self, work_item_id: uuid.UUID) -> Optional[WorkItem]:
        return self._work_items.get(work_item_id)

    def update_work_item(self, work_item: WorkItem) -> WorkItem:
        self._work_items[work_item.id] = work_item
        return work_item

    def resolve_work_item(self, work_item_id: uuid.UUID) -> WorkItem:
        wi = self._work_items[work_item_id]
        updated = wi.model_copy(update={"resolved": True, "resolved_at": datetime.now(timezone.utc)})
        self._work_items[work_item_id] = updated
        return updated

    def get_pending_work_items(self) -> list[WorkItem]:
        return [wi for wi in self._work_items.values() if not wi.resolved]

    def list_work_items(self, limit: int = 20) -> list[WorkItem]:
        items = sorted(
            self._work_items.values(),
            key=lambda wi: wi.created_at,
            reverse=True,
        )
        return items[:limit]

    def record_failure(self, work_item_id: uuid.UUID, record: FailureRecord) -> WorkItem:
        wi = self._work_items[work_item_id]
        updated = wi.model_copy(
            update={
                "failure_count": wi.failure_count + 1,
                "failure_records": wi.failure_records + [record],
            }
        )
        self._work_items[work_item_id] = updated
        return updated

    def escalate_work_item(self, work_item_id: uuid.UUID) -> WorkItem:
        wi = self._work_items[work_item_id]
        updated = wi.model_copy(update={"escalated": True})
        self._work_items[work_item_id] = updated
        return updated

    def get_escalated_items(self) -> list[WorkItem]:
        return [wi for wi in self._work_items.values() if wi.escalated]

    def get_work_item_stats(self) -> dict[str, int]:
        items = list(self._work_items.values())
        return {
            "total": len(items),
            "pending": sum(1 for wi in items if not wi.resolved),
            "resolved": sum(1 for wi in items if wi.resolved),
            "escalated": sum(1 for wi in items if wi.escalated),
        }

    def delete_old_work_items(self, days: int) -> int:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        to_delete = [
            wid for wid, wi in self._work_items.items()
            if wi.resolved and wi.resolved_at is not None and wi.resolved_at < cutoff
        ]
        for wid in to_delete:
            del self._work_items[wid]
        return len(to_delete)

    # --- Review Outcome operations ---

    def create_review_outcome(self, outcome: ReviewOutcome) -> ReviewOutcome:
        self._review_outcomes.append(outcome)
        return outcome

    def get_review_outcomes_for_concept(self, concept_id: uuid.UUID) -> list[ReviewOutcome]:
        return [o for o in self._review_outcomes if o.concept_id == concept_id]

    def list_review_outcomes(self) -> list[ReviewOutcome]:
        return list(self._review_outcomes)

    # --- Search ---

    def search_semantic(
        self, query_embedding: list[float], limit: int = 10
    ) -> list[Concept]:
        return list(self._concepts.values())[:limit]

    def search_keyword(self, query: str, limit: int = 10) -> list[Concept]:
        return [
            c for c in self._concepts.values()
            if query.lower() in c.name.lower() or query.lower() in c.description.lower()
        ][:limit]

    def search_by_file(self, file_path: str) -> list[Concept]:
        return [
            c for c in self._concepts.values()
            if any(ref.file_path == file_path for ref in c.code_references)
        ]

    # --- Graph traversal ---

    def get_neighbors(
        self,
        concept_id: uuid.UUID,
        edge_type: Optional[str] = None,
        direction: str = "both",
    ) -> list[Concept]:
        neighbor_ids: set[uuid.UUID] = set()
        for edge in self._edges.values():
            if edge_type and edge.edge_type != edge_type:
                continue
            if direction in ("outgoing", "both") and edge.source_id == concept_id:
                neighbor_ids.add(edge.target_id)
            if direction in ("incoming", "both") and edge.target_id == concept_id:
                neighbor_ids.add(edge.source_id)
        return [self._concepts[cid] for cid in neighbor_ids if cid in self._concepts]

    def traverse_graph(
        self, start_id: uuid.UUID, max_depth: int = 3
    ) -> list[Concept]:
        visited: set[uuid.UUID] = set()
        result: list[Concept] = []
        frontier = [start_id]
        depth = 0
        while frontier and depth <= max_depth:
            next_frontier: list[uuid.UUID] = []
            for cid in frontier:
                if cid in visited:
                    continue
                visited.add(cid)
                if cid in self._concepts:
                    result.append(self._concepts[cid])
                if depth < max_depth:
                    for edge in self._edges.values():
                        if edge.source_id == cid and edge.target_id not in visited:
                            next_frontier.append(edge.target_id)
            frontier = next_frontier
            depth += 1
        return result

    # --- Metrics ---

    def get_metrics(self) -> dict[str, Any]:
        return {
            "concept_count": len(self._concepts),
            "edge_count": len(self._edges),
            "work_item_count": len(self._work_items),
            "review_outcome_count": len(self._review_outcomes),
        }

    def count_covered_files(self) -> int:
        seen: set[str] = set()
        for c in self._concepts.values():
            for ref in c.code_references:
                seen.add(ref.file_path)
        return len(seen)

    def count_fresh_active_concepts(self, active_days: int = 30) -> tuple[int, int]:
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=active_days)
        active = [
            c for c in self._concepts.values()
            if c.updated_at is not None and c.updated_at >= cutoff
        ]
        fresh = sum(
            1 for c in active
            if c.last_verified is not None and c.last_verified > c.updated_at
        )
        return fresh, len(active)

    def count_blast_radius_complete(self) -> tuple[int, int]:
        total = len(self._concepts)
        with_profile = sum(1 for c in self._concepts.values() if c.impact_profile is not None)
        return with_profile, total

    # --- Bulk operations ---

    def rebuild_index(self) -> None:
        pass  # no-op in in-memory store

    # --- Librarian Activity ---

    def create_librarian_activity(self, activity: LibrarianActivity) -> LibrarianActivity:
        self._activities.append(activity)
        return activity

    def list_librarian_activities(
        self, run_id: Optional[uuid.UUID] = None
    ) -> list[LibrarianActivity]:
        if run_id is not None:
            return [a for a in self._activities if a.run_id == run_id]
        return list(self._activities)


# ---------------------------------------------------------------------------
# AC: Protocol is importable and is a Protocol class
# ---------------------------------------------------------------------------
class TestKnowledgeStoreIsProtocol:
    def test_knowledge_store_is_importable(self):
        assert KnowledgeStore is not None

    def test_knowledge_store_is_runtime_checkable(self):
        """Protocol must be decorated with @runtime_checkable for isinstance checks."""
        store = _InMemoryStore()
        assert isinstance(store, KnowledgeStore)

    def test_non_compliant_class_fails_isinstance(self):
        """An object missing protocol methods is not a KnowledgeStore."""
        class _Empty:
            pass

        assert not isinstance(_Empty(), KnowledgeStore)


# ---------------------------------------------------------------------------
# AC: All methods are synchronous def (not async def)
# ---------------------------------------------------------------------------
class TestAllMethodsSynchronous:
    def test_no_async_methods_on_protocol(self):
        """Given the protocol, when inspected, all methods are synchronous def."""
        for name, member in inspect.getmembers(KnowledgeStore, predicate=inspect.isfunction):
            assert not inspect.iscoroutinefunction(member), (
                f"KnowledgeStore.{name} is async — all methods must be synchronous"
            )


# ---------------------------------------------------------------------------
# AC: Completeness — all required method categories present
# ---------------------------------------------------------------------------
REQUIRED_METHODS = {
    # Concept CRUD
    "create_concept",
    "get_concept",
    "update_concept",
    "delete_concept",
    "list_concepts",
    # Edge CRUD
    "create_edge",
    "get_edge",
    "update_edge",
    "delete_edge",
    "list_edges",
    # Work Item operations (including the three explicitly called out)
    "create_work_item",
    "get_work_item",
    "update_work_item",
    "resolve_work_item",
    "get_pending_work_items",
    "list_work_items",
    "record_failure",
    "escalate_work_item",
    "get_escalated_items",
    # Review Outcome operations
    "create_review_outcome",
    "get_review_outcomes_for_concept",
    "list_review_outcomes",
    # Search
    "search_semantic",
    "search_keyword",
    "search_by_file",
    # Graph traversal
    "get_neighbors",
    "traverse_graph",
    # Metrics
    "get_metrics",
    # Bulk operations
    "rebuild_index",
}


class TestProtocolCompleteness:
    def test_all_required_methods_present(self):
        """Given the protocol, when checked for completeness, all categories present."""
        protocol_methods = {
            name
            for name, _ in inspect.getmembers(KnowledgeStore, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        missing = REQUIRED_METHODS - protocol_methods
        assert not missing, f"KnowledgeStore is missing methods: {sorted(missing)}"

    def test_method_count_in_range(self):
        """Protocol should have approximately 25–30 methods (Technical Notes)."""
        protocol_methods = [
            name
            for name, _ in inspect.getmembers(KnowledgeStore, predicate=inspect.isfunction)
            if not name.startswith("_")
        ]
        count = len(protocol_methods)
        assert 25 <= count <= 40, (
            f"Expected 25–40 methods, found {count}: {sorted(protocol_methods)}"
        )


# ---------------------------------------------------------------------------
# AC: All methods have docstrings
# ---------------------------------------------------------------------------
class TestMethodDocstrings:
    def test_all_methods_have_docstrings(self):
        """Every method has a docstring specifying parameters, return type, etc."""
        for name, member in inspect.getmembers(KnowledgeStore, predicate=inspect.isfunction):
            if name.startswith("_"):
                continue
            assert member.__doc__ and member.__doc__.strip(), (
                f"KnowledgeStore.{name} is missing a docstring"
            )


# ---------------------------------------------------------------------------
# AC: Write methods return the created/updated entity
# ---------------------------------------------------------------------------
class TestWriteMethodsReturnEntity:
    def setup_method(self):
        self.store: KnowledgeStore = _InMemoryStore()  # type: ignore[assignment]

    def test_create_concept_returns_concept(self):
        concept = _make_concept()
        result = self.store.create_concept(concept)
        assert isinstance(result, Concept)
        assert result.id == concept.id

    def test_update_concept_returns_concept(self):
        concept = _make_concept()
        self.store.create_concept(concept)
        updated = concept.model_copy(update={"description": "Updated."})
        result = self.store.update_concept(updated)
        assert isinstance(result, Concept)
        assert result.description == "Updated."

    def test_create_edge_returns_edge(self):
        src = _make_concept()
        tgt = _make_concept()
        self.store.create_concept(src)
        self.store.create_concept(tgt)
        edge = _make_edge(src.id, tgt.id)
        result = self.store.create_edge(edge)
        assert isinstance(result, Edge)
        assert result.id == edge.id

    def test_update_edge_returns_edge(self):
        src = _make_concept()
        tgt = _make_concept()
        self.store.create_concept(src)
        self.store.create_concept(tgt)
        edge = _make_edge(src.id, tgt.id)
        self.store.create_edge(edge)
        updated = edge.model_copy(update={"confidence": 0.8})
        result = self.store.update_edge(updated)
        assert isinstance(result, Edge)
        assert result.confidence == 0.8

    def test_create_work_item_returns_work_item(self):
        concept = _make_concept()
        self.store.create_concept(concept)
        wi = _make_work_item(concept.id)
        result = self.store.create_work_item(wi)
        assert isinstance(result, WorkItem)
        assert result.id == wi.id

    def test_record_failure_returns_updated_work_item(self):
        concept = _make_concept()
        self.store.create_concept(concept)
        wi = _make_work_item(concept.id)
        self.store.create_work_item(wi)
        record = _make_failure_record()
        result = self.store.record_failure(wi.id, record)
        assert isinstance(result, WorkItem)
        assert result.failure_count == 1
        assert len(result.failure_records) == 1

    def test_escalate_work_item_returns_updated_work_item(self):
        concept = _make_concept()
        self.store.create_concept(concept)
        wi = _make_work_item(concept.id)
        self.store.create_work_item(wi)
        result = self.store.escalate_work_item(wi.id)
        assert isinstance(result, WorkItem)
        assert result.escalated is True

    def test_resolve_work_item_returns_updated_work_item(self):
        concept = _make_concept()
        self.store.create_concept(concept)
        wi = _make_work_item(concept.id)
        self.store.create_work_item(wi)
        result = self.store.resolve_work_item(wi.id)
        assert isinstance(result, WorkItem)
        assert result.resolved is True
        assert result.resolved_at is not None

    def test_create_review_outcome_returns_review_outcome(self):
        concept = _make_concept()
        self.store.create_concept(concept)
        outcome = _make_review_outcome(concept.id)
        result = self.store.create_review_outcome(outcome)
        assert isinstance(result, ReviewOutcome)
        assert result.concept_id == concept.id


# ---------------------------------------------------------------------------
# AC: Work Item operations — record_failure, escalate, get_escalated_items
# ---------------------------------------------------------------------------
class TestWorkItemOperations:
    def setup_method(self):
        self.store: KnowledgeStore = _InMemoryStore()  # type: ignore[assignment]

    def test_get_escalated_items_returns_only_escalated(self):
        concept = _make_concept()
        self.store.create_concept(concept)
        wi1 = _make_work_item(concept.id)
        wi2 = _make_work_item(concept.id)
        self.store.create_work_item(wi1)
        self.store.create_work_item(wi2)
        self.store.escalate_work_item(wi1.id)

        escalated = self.store.get_escalated_items()
        assert len(escalated) == 1
        assert escalated[0].id == wi1.id

    def test_get_pending_work_items_excludes_resolved(self):
        concept = _make_concept()
        self.store.create_concept(concept)
        wi1 = _make_work_item(concept.id)
        wi2 = _make_work_item(concept.id)
        self.store.create_work_item(wi1)
        self.store.create_work_item(wi2)
        self.store.resolve_work_item(wi1.id)

        pending = self.store.get_pending_work_items()
        pending_ids = {wi.id for wi in pending}
        assert wi1.id not in pending_ids
        assert wi2.id in pending_ids


# ---------------------------------------------------------------------------
# AC: Search operations
# ---------------------------------------------------------------------------
class TestSearchOperations:
    def setup_method(self):
        self.store: KnowledgeStore = _InMemoryStore()  # type: ignore[assignment]

    def test_search_keyword_returns_matching_concepts(self):
        c1 = Concept(name="parse_file", description="Parses a source file.", created_by="agent")
        c2 = Concept(name="render_html", description="Renders HTML output.", created_by="agent")
        self.store.create_concept(c1)
        self.store.create_concept(c2)

        results = self.store.search_keyword("parse")
        result_names = [c.name for c in results]
        assert "parse_file" in result_names
        assert "render_html" not in result_names

    def test_search_by_file_returns_concepts_with_matching_reference(self):
        ref = CodeReference(
            symbol="fn",
            file_path="src/parser.py",
            content_hash="a" * 64,
            semantic_anchor="Parses code.",
        )
        c1 = Concept(
            name="parse_file",
            description="Parses a source file.",
            created_by="agent",
            code_references=[ref],
        )
        c2 = Concept(name="other", description="No references.", created_by="agent")
        self.store.create_concept(c1)
        self.store.create_concept(c2)

        results = self.store.search_by_file("src/parser.py")
        assert len(results) == 1
        assert results[0].id == c1.id

    def test_search_semantic_returns_list_of_concepts(self):
        concept = _make_concept()
        self.store.create_concept(concept)
        embedding = [0.1] * 384
        results = self.store.search_semantic(embedding, limit=5)
        assert isinstance(results, list)
        assert all(isinstance(c, Concept) for c in results)


# ---------------------------------------------------------------------------
# AC: Graph traversal
# ---------------------------------------------------------------------------
class TestGraphTraversal:
    def setup_method(self):
        self.store: KnowledgeStore = _InMemoryStore()  # type: ignore[assignment]

    def test_get_neighbors_returns_connected_concepts(self):
        c1 = _make_concept()
        c2 = _make_concept()
        self.store.create_concept(c1)
        self.store.create_concept(c2)
        edge = _make_edge(c1.id, c2.id)
        self.store.create_edge(edge)

        neighbors = self.store.get_neighbors(c1.id)
        assert any(n.id == c2.id for n in neighbors)

    def test_traverse_graph_returns_reachable_concepts(self):
        c1 = _make_concept()
        c2 = _make_concept()
        c3 = _make_concept()
        self.store.create_concept(c1)
        self.store.create_concept(c2)
        self.store.create_concept(c3)
        self.store.create_edge(_make_edge(c1.id, c2.id))
        self.store.create_edge(_make_edge(c2.id, c3.id))

        reachable = self.store.traverse_graph(c1.id, max_depth=2)
        reachable_ids = {c.id for c in reachable}
        assert c1.id in reachable_ids
        assert c2.id in reachable_ids
        assert c3.id in reachable_ids


# ---------------------------------------------------------------------------
# AC: Metrics
# ---------------------------------------------------------------------------
class TestMetrics:
    def setup_method(self):
        self.store: KnowledgeStore = _InMemoryStore()  # type: ignore[assignment]

    def test_get_metrics_returns_dict(self):
        metrics = self.store.get_metrics()
        assert isinstance(metrics, dict)

    def test_get_metrics_includes_concept_count(self):
        concept = _make_concept()
        self.store.create_concept(concept)
        metrics = self.store.get_metrics()
        assert "concept_count" in metrics
        assert metrics["concept_count"] >= 1
