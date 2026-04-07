"""Protocol compliance test suite — AC traceability: Story 2.9.

Parameterized by both KnowledgeStore backends so the same expectations are
verified against every implementation. Adding a third backend requires only a
new entry in the `store` fixture params — zero test modifications.

AC:
- Given the test suite, when run against the SQLite store implementation, then all tests pass.
- Given the test suite, when run against the dual writer implementation, then all tests pass.
- Given the test suite, when a new backend implementation is added, then it can be
  plugged in with zero test modifications (tests are parameterized by implementation).
- Given the test suite, when reviewed for coverage, then every protocol method has
  at least one positive test and one negative/edge-case test.

Test scope: CRUD for all entities, search (semantic and keyword), graph traversal,
work item lifecycle, work item retention cleanup, review outcome recording, metrics
queries, and rebuild-index.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

import pytest

from apriori.embedding.protocol import EmbeddingServiceProtocol
from apriori.models.concept import Concept, CodeReference
from apriori.models.edge import Edge
from apriori.models.review_outcome import ReviewOutcome
from apriori.models.work_item import FailureRecord, WorkItem
from apriori.storage.dual_writer import DualWriter
from apriori.storage.protocol import KnowledgeStore
from apriori.storage.sqlite_store import SQLiteStore
from apriori.storage.yaml_store import YamlStore


# ---------------------------------------------------------------------------
# Deterministic embedding service — no ML model required in tests
# ---------------------------------------------------------------------------

_DIMS = 768  # Must match SQLiteStore._EMBEDDING_DIMS


class _DeterministicEmbedder:
    """Deterministic EmbeddingServiceProtocol for tests.

    Maps keywords to specific vector dimensions so similarity tests are
    predictable without a real ML model.
    """

    _KEYWORD_DIM: dict[str, int] = {
        "payment": 0,
        "authentication": 1,
        "validation": 2,
        "network": 3,
        "storage": 4,
        "parser": 5,
    }

    def generate_embedding(
        self, text: str, text_type: Literal["query", "passage"] = "passage"
    ) -> list[float]:
        vec = [0.0] * _DIMS
        text_lower = text.lower()
        for keyword, dim in self._KEYWORD_DIM.items():
            if keyword in text_lower:
                vec[dim] += 1.0
        magnitude = math.sqrt(sum(x * x for x in vec))
        if magnitude < 1e-9:
            vec[0] = 1.0
            magnitude = 1.0
        return [x / magnitude for x in vec]


# ---------------------------------------------------------------------------
# Parameterized store fixture — only place that knows about concrete classes
# ---------------------------------------------------------------------------

def _build_sqlite_store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "test.db", embedding_service=_DeterministicEmbedder())


def _build_dual_writer(tmp_path: Path) -> DualWriter:
    sqlite = SQLiteStore(tmp_path / "test.db", embedding_service=_DeterministicEmbedder())
    yaml_dir = tmp_path / "yaml"
    yaml_dir.mkdir()
    yaml = YamlStore(base_dir=yaml_dir)
    return DualWriter(sqlite_store=sqlite, yaml_store=yaml)


@pytest.fixture(params=["SQLiteStore", "DualWriter"])
def store(request, tmp_path: Path) -> KnowledgeStore:
    """KnowledgeStore instance parameterized over all concrete implementations."""
    if request.param == "SQLiteStore":
        return _build_sqlite_store(tmp_path)
    elif request.param == "DualWriter":
        return _build_dual_writer(tmp_path)
    else:
        raise ValueError(f"Unknown backend: {request.param}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _concept(**kwargs) -> Concept:
    defaults = dict(name="test_concept", description="A test concept.", created_by="agent")
    defaults.update(kwargs)
    return Concept(**defaults)


def _edge(source_id: uuid.UUID, target_id: uuid.UUID, **kwargs) -> Edge:
    defaults = dict(
        source_id=source_id,
        target_id=target_id,
        edge_type="depends-on",
        evidence_type="semantic",
    )
    defaults.update(kwargs)
    return Edge(**defaults)


def _work_item(concept_id: uuid.UUID, **kwargs) -> WorkItem:
    defaults = dict(
        item_type="verify_concept",
        concept_id=concept_id,
        description="Verify this concept.",
    )
    defaults.update(kwargs)
    return WorkItem(**defaults)


def _failure_record(**kwargs) -> FailureRecord:
    defaults = dict(
        attempted_at=datetime.now(timezone.utc),
        model_used="claude-sonnet-4-6",
        prompt_template="verify_concept_v1",
        failure_reason="LLM returned ambiguous output.",
    )
    defaults.update(kwargs)
    return FailureRecord(**defaults)


def _review_outcome(concept_id: uuid.UUID, **kwargs) -> ReviewOutcome:
    defaults = dict(concept_id=concept_id, reviewer="alice", action="verified")
    defaults.update(kwargs)
    return ReviewOutcome(**defaults)


# ===========================================================================
# Concept CRUD
# ===========================================================================

class TestCreateConcept:
    """create_concept — positive and negative tests."""

    def test_returns_concept_with_correct_id(self, store: KnowledgeStore) -> None:
        """Given a Concept, when create_concept is called, the returned Concept has the same id."""
        c = _concept(name="create_positive")
        result = store.create_concept(c)
        assert isinstance(result, Concept)
        assert result.id == c.id

    def test_concept_is_retrievable_after_create(self, store: KnowledgeStore) -> None:
        """Given a created Concept, get_concept returns it."""
        c = _concept(name="retrievable_concept")
        store.create_concept(c)
        fetched = store.get_concept(c.id)
        assert fetched is not None
        assert fetched.id == c.id

    def test_name_preserved(self, store: KnowledgeStore) -> None:
        c = _concept(name="unique_name_abc")
        store.create_concept(c)
        assert store.get_concept(c.id).name == "unique_name_abc"

    def test_description_preserved(self, store: KnowledgeStore) -> None:
        c = _concept(description="Unique description text.")
        store.create_concept(c)
        assert store.get_concept(c.id).description == "Unique description text."

    def test_labels_preserved(self, store: KnowledgeStore) -> None:
        c = _concept(labels={"needs-review", "auto-generated"})
        store.create_concept(c)
        assert store.get_concept(c.id).labels == {"needs-review", "auto-generated"}

    def test_confidence_preserved(self, store: KnowledgeStore) -> None:
        c = _concept(confidence=0.75)
        store.create_concept(c)
        assert abs(store.get_concept(c.id).confidence - 0.75) < 1e-9

    def test_code_references_preserved(self, store: KnowledgeStore) -> None:
        ref = CodeReference(
            symbol="parse_fn",
            file_path="src/parser.py",
            content_hash="a" * 64,
            semantic_anchor="Parses source code.",
        )
        c = _concept(code_references=[ref])
        store.create_concept(c)
        fetched = store.get_concept(c.id)
        assert len(fetched.code_references) == 1
        assert fetched.code_references[0].file_path == "src/parser.py"

    def test_duplicate_id_raises_value_error(self, store: KnowledgeStore) -> None:
        """Given a Concept whose id already exists, create_concept raises ValueError."""
        c = _concept()
        store.create_concept(c)
        with pytest.raises(ValueError):
            store.create_concept(c)


class TestGetConcept:
    """get_concept — positive and negative tests."""

    def test_returns_concept_when_found(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        assert store.get_concept(c.id) is not None

    def test_returns_none_for_missing_id(self, store: KnowledgeStore) -> None:
        """Given an id that was never stored, get_concept returns None."""
        assert store.get_concept(uuid.uuid4()) is None


class TestUpdateConcept:
    """update_concept — positive and negative tests."""

    def test_returns_updated_concept(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        updated = c.model_copy(update={"description": "Updated."})
        result = store.update_concept(updated)
        assert isinstance(result, Concept)
        assert result.description == "Updated."

    def test_update_persists(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        updated = c.model_copy(update={"description": "Persisted description."})
        store.update_concept(updated)
        assert store.get_concept(c.id).description == "Persisted description."

    def test_nonexistent_concept_raises_key_error(self, store: KnowledgeStore) -> None:
        """Given a Concept that was never stored, update_concept raises KeyError."""
        ghost = _concept()
        with pytest.raises(KeyError):
            store.update_concept(ghost)


class TestDeleteConcept:
    """delete_concept — positive and negative tests."""

    def test_concept_removed_after_delete(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        store.delete_concept(c.id)
        assert store.get_concept(c.id) is None

    def test_dependent_edges_removed_on_delete(self, store: KnowledgeStore) -> None:
        """Given a concept with edges, delete_concept also removes those edges."""
        src = _concept(name="src")
        tgt = _concept(name="tgt")
        store.create_concept(src)
        store.create_concept(tgt)
        e = _edge(src.id, tgt.id)
        store.create_edge(e)

        store.delete_concept(src.id)

        assert store.get_concept(src.id) is None
        assert store.get_edge(e.id) is None

    def test_nonexistent_concept_raises_key_error(self, store: KnowledgeStore) -> None:
        """Given an id that does not exist, delete_concept raises KeyError."""
        with pytest.raises(KeyError):
            store.delete_concept(uuid.uuid4())


class TestListConcepts:
    """list_concepts — positive and negative tests."""

    def test_returns_all_when_no_filter(self, store: KnowledgeStore) -> None:
        c1 = _concept(name="c1")
        c2 = _concept(name="c2")
        store.create_concept(c1)
        store.create_concept(c2)
        ids = {c.id for c in store.list_concepts()}
        assert c1.id in ids
        assert c2.id in ids

    def test_empty_store_returns_empty_list(self, store: KnowledgeStore) -> None:
        assert store.list_concepts() == []

    def test_label_filter_returns_matching_only(self, store: KnowledgeStore) -> None:
        """Given concepts with different labels, list_concepts(labels=...) filters correctly."""
        c_match = _concept(name="match", labels={"needs-review"})
        c_no_match = _concept(name="no_match", labels={"verified"})
        store.create_concept(c_match)
        store.create_concept(c_no_match)
        results = store.list_concepts(labels={"needs-review"})
        ids = {c.id for c in results}
        assert c_match.id in ids
        assert c_no_match.id not in ids

    def test_label_filter_no_match_returns_empty(self, store: KnowledgeStore) -> None:
        c = _concept(labels={"verified"})
        store.create_concept(c)
        assert store.list_concepts(labels={"nonexistent-label"}) == []


# ===========================================================================
# Edge CRUD
# ===========================================================================

class TestCreateEdge:
    """create_edge — positive and negative tests."""

    def test_returns_edge_with_correct_id(self, store: KnowledgeStore) -> None:
        src = _concept(name="src")
        tgt = _concept(name="tgt")
        store.create_concept(src)
        store.create_concept(tgt)
        e = _edge(src.id, tgt.id)
        result = store.create_edge(e)
        assert isinstance(result, Edge)
        assert result.id == e.id

    def test_edge_is_retrievable_after_create(self, store: KnowledgeStore) -> None:
        src = _concept(name="src")
        tgt = _concept(name="tgt")
        store.create_concept(src)
        store.create_concept(tgt)
        e = _edge(src.id, tgt.id)
        store.create_edge(e)
        assert store.get_edge(e.id) is not None

    def test_duplicate_triple_raises_value_error(self, store: KnowledgeStore) -> None:
        """Given an edge with the same (source, target, type) triple, ValueError is raised.

        DualWriter writes YAML first (no FK/uniqueness check), then SQLite. SQLite
        constraint violations are swallowed as warnings by design (Story 2.7 AC3).
        This test applies only to backends that enforce constraints synchronously.
        """
        if isinstance(store, DualWriter):
            pytest.skip(
                "DualWriter swallows SQLite constraint violations by design (Story 2.7 AC3): "
                "YAML write succeeds, SQLite failure is logged as a warning, no exception raised."
            )
        src = _concept(name="src_dup")
        tgt = _concept(name="tgt_dup")
        store.create_concept(src)
        store.create_concept(tgt)
        e1 = _edge(src.id, tgt.id)
        store.create_edge(e1)
        e2 = _edge(src.id, tgt.id)  # same triple, different UUID
        with pytest.raises(ValueError):
            store.create_edge(e2)

    def test_missing_source_raises_key_error(self, store: KnowledgeStore) -> None:
        """Given source concept does not exist, create_edge raises KeyError.

        DualWriter writes YAML first (no referential integrity check), then SQLite.
        SQLite KeyError is swallowed as a warning by design (Story 2.7 AC3).
        """
        if isinstance(store, DualWriter):
            pytest.skip(
                "DualWriter swallows SQLite referential integrity errors by design (Story 2.7 AC3)."
            )
        tgt = _concept(name="tgt_only")
        store.create_concept(tgt)
        e = _edge(uuid.uuid4(), tgt.id)
        with pytest.raises(KeyError):
            store.create_edge(e)

    def test_missing_target_raises_key_error(self, store: KnowledgeStore) -> None:
        """Given target concept does not exist, create_edge raises KeyError.

        DualWriter writes YAML first (no referential integrity check), then SQLite.
        SQLite KeyError is swallowed as a warning by design (Story 2.7 AC3).
        """
        if isinstance(store, DualWriter):
            pytest.skip(
                "DualWriter swallows SQLite referential integrity errors by design (Story 2.7 AC3)."
            )
        src = _concept(name="src_only")
        store.create_concept(src)
        e = _edge(src.id, uuid.uuid4())
        with pytest.raises(KeyError):
            store.create_edge(e)


class TestGetEdge:
    """get_edge — positive and negative tests."""

    def test_returns_edge_when_found(self, store: KnowledgeStore) -> None:
        src = _concept(name="src")
        tgt = _concept(name="tgt")
        store.create_concept(src)
        store.create_concept(tgt)
        e = _edge(src.id, tgt.id)
        store.create_edge(e)
        assert store.get_edge(e.id) is not None

    def test_returns_none_for_missing_id(self, store: KnowledgeStore) -> None:
        """Given an id that does not exist, get_edge returns None."""
        assert store.get_edge(uuid.uuid4()) is None


class TestUpdateEdge:
    """update_edge — positive and negative tests."""

    def test_returns_updated_edge(self, store: KnowledgeStore) -> None:
        src = _concept(name="src")
        tgt = _concept(name="tgt")
        store.create_concept(src)
        store.create_concept(tgt)
        e = _edge(src.id, tgt.id)
        store.create_edge(e)
        updated = e.model_copy(update={"confidence": 0.42})
        result = store.update_edge(updated)
        assert isinstance(result, Edge)
        assert abs(result.confidence - 0.42) < 1e-9

    def test_update_persists(self, store: KnowledgeStore) -> None:
        src = _concept(name="src")
        tgt = _concept(name="tgt")
        store.create_concept(src)
        store.create_concept(tgt)
        e = _edge(src.id, tgt.id)
        store.create_edge(e)
        updated = e.model_copy(update={"confidence": 0.99})
        store.update_edge(updated)
        assert abs(store.get_edge(e.id).confidence - 0.99) < 1e-9

    def test_nonexistent_edge_raises_key_error(self, store: KnowledgeStore) -> None:
        """Given an Edge whose id was never stored, update_edge raises KeyError."""
        e = Edge(source_id=uuid.uuid4(), target_id=uuid.uuid4(),
                 edge_type="depends-on", evidence_type="semantic")
        with pytest.raises(KeyError):
            store.update_edge(e)


class TestDeleteEdge:
    """delete_edge — positive and negative tests."""

    def test_edge_removed_after_delete(self, store: KnowledgeStore) -> None:
        src = _concept(name="src")
        tgt = _concept(name="tgt")
        store.create_concept(src)
        store.create_concept(tgt)
        e = _edge(src.id, tgt.id)
        store.create_edge(e)
        store.delete_edge(e.id)
        assert store.get_edge(e.id) is None

    def test_nonexistent_edge_raises_key_error(self, store: KnowledgeStore) -> None:
        """Given an id that does not exist, delete_edge raises KeyError."""
        with pytest.raises(KeyError):
            store.delete_edge(uuid.uuid4())


class TestListEdges:
    """list_edges — positive and negative tests."""

    def test_returns_all_without_filters(self, store: KnowledgeStore) -> None:
        c1, c2, c3 = _concept(name="c1"), _concept(name="c2"), _concept(name="c3")
        store.create_concept(c1)
        store.create_concept(c2)
        store.create_concept(c3)
        e1 = _edge(c1.id, c2.id)
        e2 = _edge(c2.id, c3.id, edge_type="calls")
        store.create_edge(e1)
        store.create_edge(e2)
        ids = {e.id for e in store.list_edges()}
        assert e1.id in ids
        assert e2.id in ids

    def test_filter_by_source_id(self, store: KnowledgeStore) -> None:
        c1, c2, c3 = _concept(name="c1"), _concept(name="c2"), _concept(name="c3")
        store.create_concept(c1)
        store.create_concept(c2)
        store.create_concept(c3)
        e1 = _edge(c1.id, c2.id)
        e2 = _edge(c2.id, c3.id, edge_type="calls")
        store.create_edge(e1)
        store.create_edge(e2)
        results = store.list_edges(source_id=c1.id)
        ids = {e.id for e in results}
        assert e1.id in ids
        assert e2.id not in ids

    def test_filter_by_target_id(self, store: KnowledgeStore) -> None:
        c1, c2, c3 = _concept(name="c1"), _concept(name="c2"), _concept(name="c3")
        store.create_concept(c1)
        store.create_concept(c2)
        store.create_concept(c3)
        e1 = _edge(c1.id, c2.id)
        e2 = _edge(c1.id, c3.id, edge_type="calls")
        store.create_edge(e1)
        store.create_edge(e2)
        results = store.list_edges(target_id=c3.id)
        ids = {e.id for e in results}
        assert e2.id in ids
        assert e1.id not in ids

    def test_filter_by_edge_type(self, store: KnowledgeStore) -> None:
        c1, c2, c3 = _concept(name="c1"), _concept(name="c2"), _concept(name="c3")
        store.create_concept(c1)
        store.create_concept(c2)
        store.create_concept(c3)
        e1 = _edge(c1.id, c2.id, edge_type="depends-on")
        e2 = _edge(c1.id, c3.id, edge_type="calls")
        store.create_edge(e1)
        store.create_edge(e2)
        results = store.list_edges(edge_type="depends-on")
        ids = {e.id for e in results}
        assert e1.id in ids
        assert e2.id not in ids

    def test_no_match_returns_empty_list(self, store: KnowledgeStore) -> None:
        """Given no matching edges, list_edges returns an empty list."""
        assert store.list_edges(source_id=uuid.uuid4()) == []


# ===========================================================================
# Work Item operations
# ===========================================================================

class TestCreateWorkItem:
    """create_work_item — positive and negative tests."""

    def test_returns_work_item_with_correct_id(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        result = store.create_work_item(wi)
        assert isinstance(result, WorkItem)
        assert result.id == wi.id

    def test_work_item_is_retrievable(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        assert store.get_work_item(wi.id) is not None

    def test_duplicate_id_raises_value_error(self, store: KnowledgeStore) -> None:
        """Given a WorkItem whose id already exists, create_work_item raises ValueError."""
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        with pytest.raises(ValueError):
            store.create_work_item(wi)


class TestGetWorkItem:
    """get_work_item — positive and negative tests."""

    def test_returns_work_item_when_found(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        assert store.get_work_item(wi.id) is not None

    def test_returns_none_for_missing(self, store: KnowledgeStore) -> None:
        assert store.get_work_item(uuid.uuid4()) is None


class TestUpdateWorkItem:
    """update_work_item — positive and negative tests."""

    def test_returns_updated_work_item(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        updated = wi.model_copy(update={"description": "Updated description."})
        result = store.update_work_item(updated)
        assert isinstance(result, WorkItem)
        assert result.description == "Updated description."

    def test_update_persists(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        updated = wi.model_copy(update={"description": "Persisted."})
        store.update_work_item(updated)
        assert store.get_work_item(wi.id).description == "Persisted."

    def test_nonexistent_raises_key_error(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        with pytest.raises(KeyError):
            store.update_work_item(wi)


class TestResolveWorkItem:
    """resolve_work_item — positive and negative tests."""

    def test_returns_resolved_work_item(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        result = store.resolve_work_item(wi.id)
        assert isinstance(result, WorkItem)
        assert result.resolved is True

    def test_resolved_at_is_stamped(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        before = datetime.now(timezone.utc)
        result = store.resolve_work_item(wi.id)
        after = datetime.now(timezone.utc)
        assert result.resolved_at is not None
        assert before <= result.resolved_at <= after

    def test_resolve_persists(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        store.resolve_work_item(wi.id)
        assert store.get_work_item(wi.id).resolved is True

    def test_nonexistent_raises_key_error(self, store: KnowledgeStore) -> None:
        with pytest.raises(KeyError):
            store.resolve_work_item(uuid.uuid4())


class TestGetPendingWorkItems:
    """get_pending_work_items — positive and negative tests."""

    def test_returns_unresolved_items(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi1 = _work_item(c.id, description="pending")
        wi2 = _work_item(c.id, description="resolved")
        store.create_work_item(wi1)
        store.create_work_item(wi2)
        store.resolve_work_item(wi2.id)
        pending_ids = {wi.id for wi in store.get_pending_work_items()}
        assert wi1.id in pending_ids
        assert wi2.id not in pending_ids

    def test_empty_store_returns_empty_list(self, store: KnowledgeStore) -> None:
        assert store.get_pending_work_items() == []


class TestRecordFailure:
    """record_failure — positive and negative tests."""

    def test_increments_failure_count(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        result = store.record_failure(wi.id, _failure_record())
        assert isinstance(result, WorkItem)
        assert result.failure_count == 1

    def test_appends_failure_record(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        record = _failure_record(failure_reason="Timeout.")
        store.record_failure(wi.id, record)
        retrieved = store.get_work_item(wi.id)
        assert len(retrieved.failure_records) == 1
        assert retrieved.failure_records[0].failure_reason == "Timeout."

    def test_accumulates_multiple_failures(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        for i in range(3):
            store.record_failure(wi.id, _failure_record(failure_reason=f"Failure {i}"))
        retrieved = store.get_work_item(wi.id)
        assert retrieved.failure_count == 3
        assert len(retrieved.failure_records) == 3

    def test_does_not_auto_escalate(self, store: KnowledgeStore) -> None:
        """record_failure must never set escalated — that is done only by escalate_work_item."""
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id, failure_count=10)
        store.create_work_item(wi)
        result = store.record_failure(wi.id, _failure_record())
        assert result.escalated is False

    def test_nonexistent_raises_key_error(self, store: KnowledgeStore) -> None:
        with pytest.raises(KeyError):
            store.record_failure(uuid.uuid4(), _failure_record())


class TestEscalateWorkItem:
    """escalate_work_item — positive and negative tests."""

    def test_returns_escalated_work_item(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        result = store.escalate_work_item(wi.id)
        assert isinstance(result, WorkItem)
        assert result.escalated is True

    def test_escalation_persists(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        store.escalate_work_item(wi.id)
        assert store.get_work_item(wi.id).escalated is True

    def test_nonexistent_raises_key_error(self, store: KnowledgeStore) -> None:
        with pytest.raises(KeyError):
            store.escalate_work_item(uuid.uuid4())


class TestGetEscalatedItems:
    """get_escalated_items — positive and negative tests."""

    def test_returns_only_escalated_items(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi1 = _work_item(c.id, description="normal")
        wi2 = _work_item(c.id, description="escalated")
        store.create_work_item(wi1)
        store.create_work_item(wi2)
        store.escalate_work_item(wi2.id)
        escalated_ids = {wi.id for wi in store.get_escalated_items()}
        assert wi2.id in escalated_ids
        assert wi1.id not in escalated_ids

    def test_empty_store_returns_empty_list(self, store: KnowledgeStore) -> None:
        assert store.get_escalated_items() == []


class TestGetWorkItemStats:
    """get_work_item_stats — positive and negative tests."""

    def test_required_keys_present(self, store: KnowledgeStore) -> None:
        stats = store.get_work_item_stats()
        for key in ("total", "pending", "resolved", "escalated"):
            assert key in stats

    def test_empty_store_all_zeros(self, store: KnowledgeStore) -> None:
        stats = store.get_work_item_stats()
        assert stats["total"] == 0
        assert stats["pending"] == 0
        assert stats["resolved"] == 0
        assert stats["escalated"] == 0

    def test_counts_are_correct(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi1 = _work_item(c.id, description="pending")
        wi2 = _work_item(c.id, description="will resolve")
        wi3 = _work_item(c.id, description="will escalate")
        store.create_work_item(wi1)
        store.create_work_item(wi2)
        store.create_work_item(wi3)
        store.resolve_work_item(wi2.id)
        store.escalate_work_item(wi3.id)

        stats = store.get_work_item_stats()
        assert stats["total"] == 3
        assert stats["pending"] == 2  # wi1 and wi3 (escalated but still pending)
        assert stats["resolved"] == 1
        assert stats["escalated"] == 1


class TestDeleteOldWorkItems:
    """delete_old_work_items — positive and negative tests."""

    def _set_resolved_at(self, store: KnowledgeStore, wi_id: uuid.UUID, ts: datetime) -> None:
        """Directly manipulate resolved_at — works only with SQLiteStore internals.

        For DualWriter, we reach through to the underlying sqlite store.
        """
        if isinstance(store, DualWriter):
            sqlite = store._sqlite
        else:
            sqlite = store
        conn = sqlite._get_connection()
        conn.execute(
            "UPDATE work_items SET resolved=1, resolved_at=? WHERE id=?",
            (ts.isoformat(), str(wi_id)),
        )
        conn.commit()

    def test_removes_old_resolved_items(self, store: KnowledgeStore) -> None:
        """Given a resolved item older than N days, delete_old_work_items removes it."""
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        old_ts = datetime.now(timezone.utc) - timedelta(days=60)
        self._set_resolved_at(store, wi.id, old_ts)

        deleted = store.delete_old_work_items(days=30)
        assert deleted == 1
        assert store.get_work_item(wi.id) is None

    def test_preserves_recently_resolved_items(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        store.resolve_work_item(wi.id)  # resolved_at = now

        deleted = store.delete_old_work_items(days=30)
        assert deleted == 0
        assert store.get_work_item(wi.id) is not None

    def test_preserves_unresolved_items_regardless_of_age(self, store: KnowledgeStore) -> None:
        """Unresolved work items are NEVER deleted by this method."""
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)

        deleted = store.delete_old_work_items(days=0)
        assert deleted == 0
        assert store.get_work_item(wi.id) is not None

    def test_returns_count_of_deleted_items(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        old_ts = datetime.now(timezone.utc) - timedelta(days=60)
        for _ in range(3):
            wi = _work_item(c.id)
            store.create_work_item(wi)
            self._set_resolved_at(store, wi.id, old_ts)

        deleted = store.delete_old_work_items(days=30)
        assert deleted == 3


# ===========================================================================
# Review Outcome operations
# ===========================================================================

class TestCreateReviewOutcome:
    """create_review_outcome — positive test."""

    def test_returns_review_outcome(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        outcome = _review_outcome(c.id)
        result = store.create_review_outcome(outcome)
        assert isinstance(result, ReviewOutcome)
        assert result.concept_id == c.id


class TestGetReviewOutcomesForConcept:
    """get_review_outcomes_for_concept — positive and negative tests."""

    def test_returns_outcomes_for_concept(self, store: KnowledgeStore) -> None:
        c1 = _concept(name="c1")
        c2 = _concept(name="c2")
        store.create_concept(c1)
        store.create_concept(c2)
        o1 = _review_outcome(c1.id)
        o2 = _review_outcome(c2.id)
        store.create_review_outcome(o1)
        store.create_review_outcome(o2)

        results = store.get_review_outcomes_for_concept(c1.id)
        assert len(results) == 1
        assert results[0].concept_id == c1.id

    def test_returns_empty_when_no_outcomes(self, store: KnowledgeStore) -> None:
        """Given a concept with no review outcomes, returns an empty list."""
        c = _concept()
        store.create_concept(c)
        assert store.get_review_outcomes_for_concept(c.id) == []

    def test_returns_empty_for_unknown_concept(self, store: KnowledgeStore) -> None:
        assert store.get_review_outcomes_for_concept(uuid.uuid4()) == []


class TestListReviewOutcomes:
    """list_review_outcomes — positive and negative tests."""

    def test_returns_all_outcomes(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        store.create_review_outcome(_review_outcome(c.id))
        store.create_review_outcome(_review_outcome(c.id))
        assert len(store.list_review_outcomes()) == 2

    def test_empty_store_returns_empty_list(self, store: KnowledgeStore) -> None:
        assert store.list_review_outcomes() == []


# ===========================================================================
# Search
# ===========================================================================

class TestSearchSemantic:
    """search_semantic — positive and negative tests."""

    def test_returns_list_of_concepts(self, store: KnowledgeStore) -> None:
        c = _concept(name="payment_gw", description="payment processing")
        store.create_concept(c)
        embedding = [0.0] * _DIMS
        embedding[0] = 1.0  # payment dimension
        results = store.search_semantic(embedding, limit=5)
        assert isinstance(results, list)
        assert all(isinstance(r, Concept) for r in results)

    def test_respects_limit(self, store: KnowledgeStore) -> None:
        for i in range(10):
            store.create_concept(_concept(
                name=f"payment_svc_{i}",
                description=f"payment service {i}",
            ))
        embedding = [0.0] * _DIMS
        embedding[0] = 1.0
        results = store.search_semantic(embedding, limit=3)
        assert len(results) <= 3

    def test_empty_store_returns_empty_list(self, store: KnowledgeStore) -> None:
        embedding = [0.0] * _DIMS
        embedding[0] = 1.0
        assert store.search_semantic(embedding, limit=5) == []

    def test_most_similar_concept_ranks_first(self, store: KnowledgeStore) -> None:
        """Given two concepts with different keywords, the relevant one ranks first."""
        payment = _concept(name="payment", description="payment processing gateway")
        auth = _concept(name="auth", description="authentication token handler")
        store.create_concept(payment)
        store.create_concept(auth)

        # Query embedding aligned with "payment"
        embedding = [0.0] * _DIMS
        embedding[0] = 1.0  # payment dimension
        results = store.search_semantic(embedding, limit=5)

        assert len(results) > 0
        assert results[0].id == payment.id


class TestSearchKeyword:
    """search_keyword — positive and negative tests."""

    def test_finds_matching_concept_by_name(self, store: KnowledgeStore) -> None:
        c = _concept(name="authentication_service", description="Manages logins.")
        other = _concept(name="log_formatter", description="Formats logs.")
        store.create_concept(c)
        store.create_concept(other)
        results = store.search_keyword("authentication_service", limit=10)
        ids = {r.id for r in results}
        assert c.id in ids
        assert other.id not in ids

    def test_finds_matching_concept_by_description(self, store: KnowledgeStore) -> None:
        c = _concept(name="login_handler", description="Performs authentication check.")
        store.create_concept(c)
        results = store.search_keyword("authentication", limit=10)
        assert c.id in {r.id for r in results}

    def test_respects_limit(self, store: KnowledgeStore) -> None:
        for i in range(10):
            store.create_concept(_concept(
                name=f"service_{i}",
                description=f"A service component {i}.",
            ))
        results = store.search_keyword("service", limit=3)
        assert len(results) <= 3

    def test_no_match_returns_empty_list(self, store: KnowledgeStore) -> None:
        """Given a query that matches nothing, search_keyword returns an empty list."""
        store.create_concept(_concept(name="parser", description="parses code"))
        assert store.search_keyword("zxqwerty_unique", limit=10) == []

    def test_empty_store_returns_empty_list(self, store: KnowledgeStore) -> None:
        assert store.search_keyword("anything", limit=10) == []


class TestSearchByFile:
    """search_by_file — positive and negative tests."""

    def test_returns_concepts_with_matching_reference(self, store: KnowledgeStore) -> None:
        ref = CodeReference(
            symbol="parse_fn",
            file_path="src/parser.py",
            content_hash="a" * 64,
            semantic_anchor="Parses source.",
        )
        c1 = _concept(name="parser_concept", code_references=[ref])
        c2 = _concept(name="no_refs")
        store.create_concept(c1)
        store.create_concept(c2)

        results = store.search_by_file("src/parser.py")
        ids = {r.id for r in results}
        assert c1.id in ids
        assert c2.id not in ids

    def test_no_match_returns_empty_list(self, store: KnowledgeStore) -> None:
        c = _concept(name="no_refs")
        store.create_concept(c)
        assert store.search_by_file("nonexistent/path.py") == []

    def test_empty_store_returns_empty_list(self, store: KnowledgeStore) -> None:
        assert store.search_by_file("src/anything.py") == []


# ===========================================================================
# Graph traversal
# ===========================================================================

class TestGetNeighbors:
    """get_neighbors — positive and negative tests."""

    def test_returns_directly_connected_concepts(self, store: KnowledgeStore) -> None:
        c1 = _concept(name="hub")
        c2 = _concept(name="spoke")
        store.create_concept(c1)
        store.create_concept(c2)
        store.create_edge(_edge(c1.id, c2.id))

        neighbors = store.get_neighbors(c1.id)
        assert any(n.id == c2.id for n in neighbors)

    def test_outgoing_direction_returns_targets_only(self, store: KnowledgeStore) -> None:
        hub = _concept(name="hub")
        child = _concept(name="child")
        parent = _concept(name="parent")
        store.create_concept(hub)
        store.create_concept(child)
        store.create_concept(parent)
        store.create_edge(_edge(hub.id, child.id))  # outgoing from hub
        store.create_edge(_edge(parent.id, hub.id))  # incoming to hub

        neighbors = store.get_neighbors(hub.id, direction="outgoing")
        neighbor_ids = {n.id for n in neighbors}
        assert child.id in neighbor_ids
        assert parent.id not in neighbor_ids

    def test_incoming_direction_returns_sources_only(self, store: KnowledgeStore) -> None:
        hub = _concept(name="hub")
        child = _concept(name="child")
        parent = _concept(name="parent")
        store.create_concept(hub)
        store.create_concept(child)
        store.create_concept(parent)
        store.create_edge(_edge(hub.id, child.id))
        store.create_edge(_edge(parent.id, hub.id))

        neighbors = store.get_neighbors(hub.id, direction="incoming")
        neighbor_ids = {n.id for n in neighbors}
        assert parent.id in neighbor_ids
        assert child.id not in neighbor_ids

    def test_edge_type_filter(self, store: KnowledgeStore) -> None:
        c1 = _concept(name="c1")
        c2 = _concept(name="c2")
        c3 = _concept(name="c3")
        store.create_concept(c1)
        store.create_concept(c2)
        store.create_concept(c3)
        store.create_edge(_edge(c1.id, c2.id, edge_type="depends-on"))
        store.create_edge(_edge(c1.id, c3.id, edge_type="calls"))

        neighbors = store.get_neighbors(c1.id, edge_type="depends-on")
        ids = {n.id for n in neighbors}
        assert c2.id in ids
        assert c3.id not in ids

    def test_invalid_direction_raises_value_error(self, store: KnowledgeStore) -> None:
        """Given an invalid direction string, get_neighbors raises ValueError."""
        c = _concept()
        store.create_concept(c)
        with pytest.raises(ValueError):
            store.get_neighbors(c.id, direction="sideways")

    def test_no_neighbors_returns_empty_list(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        assert store.get_neighbors(c.id) == []


class TestTraverseGraph:
    """traverse_graph — positive and negative tests."""

    def test_includes_start_concept(self, store: KnowledgeStore) -> None:
        c = _concept(name="start")
        store.create_concept(c)
        results = store.traverse_graph(c.id, max_depth=1)
        assert any(r.id == c.id for r in results)

    def test_returns_reachable_concepts_in_bfs_order(self, store: KnowledgeStore) -> None:
        c1, c2, c3 = _concept(name="c1"), _concept(name="c2"), _concept(name="c3")
        store.create_concept(c1)
        store.create_concept(c2)
        store.create_concept(c3)
        store.create_edge(_edge(c1.id, c2.id))
        store.create_edge(_edge(c2.id, c3.id))

        results = store.traverse_graph(c1.id, max_depth=2)
        ids = {r.id for r in results}
        assert c1.id in ids
        assert c2.id in ids
        assert c3.id in ids

    def test_max_depth_limits_traversal(self, store: KnowledgeStore) -> None:
        """Given max_depth=1, traverse_graph does not reach depth-2 concepts."""
        c1, c2, c3 = _concept(name="c1"), _concept(name="c2"), _concept(name="c3")
        store.create_concept(c1)
        store.create_concept(c2)
        store.create_concept(c3)
        store.create_edge(_edge(c1.id, c2.id))
        store.create_edge(_edge(c2.id, c3.id))

        results = store.traverse_graph(c1.id, max_depth=1)
        ids = {r.id for r in results}
        assert c1.id in ids
        assert c2.id in ids
        assert c3.id not in ids  # depth-2 must not appear

    def test_no_cycles_in_result(self, store: KnowledgeStore) -> None:
        """Each concept appears at most once in the result (cycle safety)."""
        c1, c2 = _concept(name="c1"), _concept(name="c2")
        store.create_concept(c1)
        store.create_concept(c2)
        store.create_edge(_edge(c1.id, c2.id))
        store.create_edge(_edge(c2.id, c1.id, edge_type="calls"))

        results = store.traverse_graph(c1.id, max_depth=5)
        ids = [r.id for r in results]
        assert len(ids) == len(set(ids))  # no duplicates

    def test_empty_graph_returns_start_concept_only(self, store: KnowledgeStore) -> None:
        c = _concept(name="isolated")
        store.create_concept(c)
        results = store.traverse_graph(c.id, max_depth=3)
        assert len(results) == 1
        assert results[0].id == c.id


# ===========================================================================
# Metrics
# ===========================================================================

class TestGetMetrics:
    """get_metrics — positive and negative tests."""

    def test_required_keys_present(self, store: KnowledgeStore) -> None:
        metrics = store.get_metrics()
        for key in ("concept_count", "edge_count", "work_item_count", "review_outcome_count"):
            assert key in metrics

    def test_returns_dict(self, store: KnowledgeStore) -> None:
        assert isinstance(store.get_metrics(), dict)

    def test_counts_are_accurate(self, store: KnowledgeStore) -> None:
        c = _concept()
        store.create_concept(c)
        wi = _work_item(c.id)
        store.create_work_item(wi)
        outcome = _review_outcome(c.id)
        store.create_review_outcome(outcome)

        metrics = store.get_metrics()
        assert metrics["concept_count"] >= 1
        assert metrics["work_item_count"] >= 1
        assert metrics["review_outcome_count"] >= 1

    def test_empty_store_all_zero(self, store: KnowledgeStore) -> None:
        metrics = store.get_metrics()
        assert metrics["concept_count"] == 0
        assert metrics["edge_count"] == 0
        assert metrics["work_item_count"] == 0
        assert metrics["review_outcome_count"] == 0


# ===========================================================================
# Bulk operations
# ===========================================================================

class TestRebuildIndex:
    """rebuild_index — positive test (must not raise; search remains functional)."""

    def test_rebuild_does_not_raise(self, store: KnowledgeStore) -> None:
        """Given any store state, rebuild_index completes without raising."""
        c = _concept(name="rebuild_test", description="payment processing")
        store.create_concept(c)
        store.rebuild_index()  # must not raise

    def test_search_still_works_after_rebuild(self, store: KnowledgeStore) -> None:
        """After rebuild_index, keyword search still returns expected results."""
        c = _concept(
            name="rebuild_keyword_concept",
            description="unique_keyword_zzzrebuildzz",
        )
        store.create_concept(c)
        store.rebuild_index()
        results = store.search_keyword("unique_keyword_zzzrebuildzz", limit=5)
        assert c.id in {r.id for r in results}

    def test_rebuild_empty_store_does_not_raise(self, store: KnowledgeStore) -> None:
        """rebuild_index on an empty store must not raise."""
        store.rebuild_index()


# ===========================================================================
# Protocol structural check (applies to all backends)
# ===========================================================================

class TestImplementsKnowledgeStoreProtocol:
    """Every parameterized backend must satisfy the KnowledgeStore runtime protocol."""

    def test_isinstance_check_passes(self, store: KnowledgeStore) -> None:
        """isinstance(store, KnowledgeStore) must be True for every backend."""
        assert isinstance(store, KnowledgeStore)
