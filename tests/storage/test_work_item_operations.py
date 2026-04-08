"""Tests for SQLiteStore work item operations — AC traceability: Story 2.3b.

AC-1: Given an Edge referencing a non-existent concept, when create_edge is
      called, then a referential integrity error (KeyError) is raised.
AC-2: Given a WorkItem, when record_failure is called with a FailureRecord,
      then the record is appended to failure_records JSON array and
      failure_count is incremented.
AC-3: Given a WorkItem with failure_count=2 and escalation threshold of 3,
      when record_failure is called, then failure_count becomes 3 but
      escalated remains False.
AC-4: Given a WorkItem, when escalate_work_item is called, then escalated
      is set to True.
AC-5: Given multiple threads reading concurrently, when the store is accessed,
      then no locking errors occur (WAL mode enables concurrent reads).
AC-6: Given work items in various states, when get_work_item_stats is called,
      then it returns aggregate counts.
AC-7: Given resolved work items older than retention period, when
      delete_old_work_items(days) is called, then resolved items older than
      the specified days are deleted.
AC-8: Given an unresolved WorkItem, when resolve_work_item is called, then
      resolved is set to True and resolved_at is stamped.

DoD coverage: work item lifecycle, retention cleanup, concurrent reads,
              edge referential integrity, failure tracking.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.models.work_item import FailureRecord, WorkItem
from apriori.storage.sqlite_store import SQLiteStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_work_items.db"


@pytest.fixture
def store(db_path: Path) -> SQLiteStore:
    return SQLiteStore(db_path)


def _make_concept(**kwargs) -> Concept:
    defaults = dict(name="test_concept", description="A test concept.", created_by="agent")
    defaults.update(kwargs)
    return Concept(**defaults)


def _make_work_item(concept_id: uuid.UUID, **kwargs) -> WorkItem:
    defaults = dict(
        concept_id=concept_id,
        item_type="verify_concept",
        description="Verify this concept.",
    )
    defaults.update(kwargs)
    return WorkItem(**defaults)


def _make_failure_record(**kwargs) -> FailureRecord:
    defaults = dict(
        attempted_at=datetime.now(timezone.utc),
        model_used="claude-sonnet-4-6",
        prompt_template="default_librarian_v1",
        failure_reason="LLM returned incomplete response.",
    )
    defaults.update(kwargs)
    return FailureRecord(**defaults)


def _make_edge(source_id: uuid.UUID, target_id: uuid.UUID, **kwargs) -> Edge:
    defaults = dict(
        source_id=source_id,
        target_id=target_id,
        edge_type="depends-on",
        evidence_type="semantic",
    )
    defaults.update(kwargs)
    return Edge(**defaults)


# ---------------------------------------------------------------------------
# AC-1: Edge referential integrity
# ---------------------------------------------------------------------------

class TestEdgeReferentialIntegrity:
    """AC-1: create_edge with non-existent concept raises KeyError."""

    def test_create_edge_with_missing_source_raises_key_error(self, store: SQLiteStore):
        """Given a missing source concept, when create_edge is called, KeyError is raised."""
        tgt = _make_concept(name="target")
        store.create_concept(tgt)
        edge = _make_edge(uuid.uuid4(), tgt.id)  # source does not exist
        with pytest.raises(KeyError):
            store.create_edge(edge)

    def test_create_edge_with_missing_target_raises_key_error(self, store: SQLiteStore):
        """Given a missing target concept, when create_edge is called, KeyError is raised."""
        src = _make_concept(name="source")
        store.create_concept(src)
        edge = _make_edge(src.id, uuid.uuid4())  # target does not exist
        with pytest.raises(KeyError):
            store.create_edge(edge)

    def test_create_edge_with_both_missing_raises_key_error(self, store: SQLiteStore):
        """Given both concepts missing, when create_edge is called, KeyError is raised."""
        edge = _make_edge(uuid.uuid4(), uuid.uuid4())
        with pytest.raises(KeyError):
            store.create_edge(edge)

    def test_create_edge_with_valid_concepts_succeeds(self, store: SQLiteStore):
        """Given both concepts exist, when create_edge is called, edge is persisted."""
        src = _make_concept(name="source")
        tgt = _make_concept(name="target")
        store.create_concept(src)
        store.create_concept(tgt)
        edge = _make_edge(src.id, tgt.id)
        result = store.create_edge(edge)
        assert result.id == edge.id


# ---------------------------------------------------------------------------
# AC-2: record_failure appends record and increments count
# ---------------------------------------------------------------------------

class TestRecordFailure:
    """AC-2: record_failure appends FailureRecord and increments failure_count."""

    def test_record_failure_increments_failure_count(self, store: SQLiteStore):
        """Given a WorkItem with failure_count=0, when record_failure is called,
        failure_count becomes 1."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        record = _make_failure_record()
        updated = store.record_failure(wi.id, record)

        assert updated.failure_count == 1

    def test_record_failure_appends_to_failure_records(self, store: SQLiteStore):
        """Given a WorkItem, when record_failure is called, record is appended."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        record = _make_failure_record(failure_reason="Timeout error.")
        store.record_failure(wi.id, record)

        retrieved = store.get_work_item(wi.id)
        assert len(retrieved.failure_records) == 1
        assert retrieved.failure_records[0].failure_reason == "Timeout error."

    def test_record_failure_multiple_times_accumulates_records(self, store: SQLiteStore):
        """Given multiple record_failure calls, all records accumulate in JSON array."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        for i in range(3):
            record = _make_failure_record(failure_reason=f"Failure {i}")
            store.record_failure(wi.id, record)

        retrieved = store.get_work_item(wi.id)
        assert retrieved.failure_count == 3
        assert len(retrieved.failure_records) == 3

    def test_record_failure_preserves_all_fields(self, store: SQLiteStore):
        """Given a FailureRecord with all fields, all are preserved after record_failure."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        record = _make_failure_record(
            model_used="claude-opus-4-6",
            prompt_template="deep_analysis_v2",
            quality_scores={"relevance": 0.4, "completeness": 0.6},
            reviewer_feedback="Try a more focused prompt.",
        )
        store.record_failure(wi.id, record)

        retrieved = store.get_work_item(wi.id)
        fr = retrieved.failure_records[0]
        assert fr.model_used == "claude-opus-4-6"
        assert fr.prompt_template == "deep_analysis_v2"
        assert fr.quality_scores == {"relevance": 0.4, "completeness": 0.6}
        assert fr.reviewer_feedback == "Try a more focused prompt."

    def test_record_failure_raises_key_error_for_missing_item(self, store: SQLiteStore):
        """Given a non-existent work item id, record_failure raises KeyError."""
        record = _make_failure_record()
        with pytest.raises(KeyError):
            store.record_failure(uuid.uuid4(), record)


# ---------------------------------------------------------------------------
# AC-3: record_failure does not auto-escalate before threshold
# ---------------------------------------------------------------------------

class TestEscalationThreshold:
    """AC-3: failure_count=2 → record_failure → count=3, escalated remains False."""

    def test_record_failure_does_not_auto_escalate_below_threshold(self, store: SQLiteStore):
        """Given failure_count=2, when record_failure is called, escalated stays False."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id, failure_count=2)
        store.create_work_item(wi)

        record = _make_failure_record()
        updated = store.record_failure(wi.id, record)

        assert updated.failure_count == 3
        assert updated.escalated is False

    def test_escalated_flag_is_independent_of_failure_count(self, store: SQLiteStore):
        """record_failure never sets escalated — that is only set by escalate_work_item."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id, failure_count=10)
        store.create_work_item(wi)

        record = _make_failure_record()
        updated = store.record_failure(wi.id, record)

        assert updated.escalated is False


# ---------------------------------------------------------------------------
# AC-4: escalate_work_item sets escalated=True
# ---------------------------------------------------------------------------

class TestEscalateWorkItem:
    """AC-4: escalate_work_item sets escalated to True."""

    def test_escalate_sets_escalated_true(self, store: SQLiteStore):
        """Given an unescalated WorkItem, escalate_work_item sets escalated=True."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        updated = store.escalate_work_item(wi.id)

        assert updated.escalated is True

    def test_escalate_persists_to_store(self, store: SQLiteStore):
        """After escalate_work_item, get_work_item returns escalated=True."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        store.escalate_work_item(wi.id)
        retrieved = store.get_work_item(wi.id)

        assert retrieved.escalated is True

    def test_escalate_nonexistent_item_raises_key_error(self, store: SQLiteStore):
        """Given a non-existent work item id, escalate_work_item raises KeyError."""
        with pytest.raises(KeyError):
            store.escalate_work_item(uuid.uuid4())

    def test_get_escalated_items_returns_escalated_only(self, store: SQLiteStore):
        """get_escalated_items returns only escalated work items."""
        concept = _make_concept()
        store.create_concept(concept)
        wi1 = _make_work_item(concept.id, description="normal item")
        wi2 = _make_work_item(concept.id, description="escalated item")
        store.create_work_item(wi1)
        store.create_work_item(wi2)

        store.escalate_work_item(wi2.id)
        escalated = store.get_escalated_items()

        ids = {item.id for item in escalated}
        assert wi2.id in ids
        assert wi1.id not in ids


# ---------------------------------------------------------------------------
# AC-4b: list_work_items returns newest-first with limit
# ---------------------------------------------------------------------------

class TestListWorkItems:
    """list_work_items returns most recent work items ordered by created_at desc."""

    def test_list_work_items_orders_newest_first_with_limit(self, store: SQLiteStore):
        concept = _make_concept()
        store.create_concept(concept)

        older = _make_work_item(
            concept.id,
            description="older",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        newer = _make_work_item(
            concept.id,
            description="newer",
            created_at=datetime.now(timezone.utc),
        )
        middle = _make_work_item(
            concept.id,
            description="middle",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        )
        store.create_work_item(older)
        store.create_work_item(newer)
        store.create_work_item(middle)

        recent = store.list_work_items(limit=2)
        assert [item.description for item in recent] == ["newer", "middle"]


# ---------------------------------------------------------------------------
# AC-5: Concurrent reads — WAL mode, no locking errors
# ---------------------------------------------------------------------------

class TestConcurrentReads:
    """AC-5: Multiple concurrent readers succeed without locking errors."""

    def test_concurrent_reads_do_not_cause_locking_errors(self, store: SQLiteStore):
        """Given WAL mode, multiple threads can read concurrently without errors."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        errors: list[Exception] = []
        results: list[WorkItem] = []
        lock = threading.Lock()

        def read_in_thread():
            try:
                item = store.get_work_item(wi.id)
                with lock:
                    if item:
                        results.append(item)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=read_in_thread) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Locking errors in concurrent reads: {errors}"
        assert len(results) == 20

    def test_concurrent_reads_and_writes_do_not_conflict(self, store: SQLiteStore):
        """Given WAL mode, concurrent reads and writes do not block each other."""
        concept = _make_concept()
        store.create_concept(concept)

        errors: list[Exception] = []
        lock = threading.Lock()

        def write_in_thread(i: int):
            try:
                wi = _make_work_item(concept.id, description=f"item {i}")
                store.create_work_item(wi)
            except Exception as e:
                with lock:
                    errors.append(e)

        def read_in_thread():
            try:
                store.get_pending_work_items()
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = (
            [threading.Thread(target=write_in_thread, args=(i,)) for i in range(5)]
            + [threading.Thread(target=read_in_thread) for _ in range(10)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent read/write: {errors}"


# ---------------------------------------------------------------------------
# AC-6: get_work_item_stats returns aggregate counts
# ---------------------------------------------------------------------------

class TestGetWorkItemStats:
    """AC-6: get_work_item_stats returns aggregate counts for various states."""

    def test_empty_store_returns_zero_counts(self, store: SQLiteStore):
        """Given an empty store, get_work_item_stats returns all zeros."""
        stats = store.get_work_item_stats()
        assert stats["total"] == 0
        assert stats["pending"] == 0
        assert stats["resolved"] == 0
        assert stats["escalated"] == 0

    def test_stats_count_all_items(self, store: SQLiteStore):
        """Given N work items, total equals N."""
        concept = _make_concept()
        store.create_concept(concept)
        for _ in range(3):
            wi = _make_work_item(concept.id)
            store.create_work_item(wi)

        stats = store.get_work_item_stats()
        assert stats["total"] == 3

    def test_stats_count_pending_items(self, store: SQLiteStore):
        """Pending count equals number of unresolved items."""
        concept = _make_concept()
        store.create_concept(concept)
        wi1 = _make_work_item(concept.id, description="pending 1")
        wi2 = _make_work_item(concept.id, description="pending 2")
        wi3 = _make_work_item(concept.id, description="will be resolved")
        store.create_work_item(wi1)
        store.create_work_item(wi2)
        store.create_work_item(wi3)
        store.resolve_work_item(wi3.id)

        stats = store.get_work_item_stats()
        assert stats["pending"] == 2
        assert stats["resolved"] == 1

    def test_stats_count_escalated_items(self, store: SQLiteStore):
        """Escalated count equals number of escalated items."""
        concept = _make_concept()
        store.create_concept(concept)
        wi1 = _make_work_item(concept.id, description="normal")
        wi2 = _make_work_item(concept.id, description="escalated")
        store.create_work_item(wi1)
        store.create_work_item(wi2)
        store.escalate_work_item(wi2.id)

        stats = store.get_work_item_stats()
        assert stats["escalated"] == 1
        assert stats["total"] == 2

    def test_stats_keys_are_present(self, store: SQLiteStore):
        """get_work_item_stats always returns the required keys."""
        stats = store.get_work_item_stats()
        assert "total" in stats
        assert "pending" in stats
        assert "resolved" in stats
        assert "escalated" in stats


# ---------------------------------------------------------------------------
# AC-7: delete_old_work_items removes resolved items older than retention period
# ---------------------------------------------------------------------------

class TestDeleteOldWorkItems:
    """AC-7: delete_old_work_items removes resolved items older than N days."""

    def test_delete_old_removes_old_resolved_items(self, store: SQLiteStore):
        """Given a resolved item older than N days, delete_old_work_items removes it."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        # Manually resolve with an old resolved_at
        old_time = datetime.now(timezone.utc) - timedelta(days=35)
        from apriori.storage.sqlite_store import SQLiteStore as _S
        conn = store._get_connection()
        conn.execute(
            "UPDATE work_items SET resolved=1, resolved_at=? WHERE id=?",
            (old_time.isoformat(), str(wi.id)),
        )
        conn.commit()

        deleted = store.delete_old_work_items(days=30)
        assert deleted == 1
        assert store.get_work_item(wi.id) is None

    def test_delete_old_preserves_recent_resolved_items(self, store: SQLiteStore):
        """Given a recently resolved item, delete_old_work_items keeps it."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)
        store.resolve_work_item(wi.id)  # resolved_at = now

        deleted = store.delete_old_work_items(days=30)
        assert deleted == 0
        assert store.get_work_item(wi.id) is not None

    def test_delete_old_preserves_unresolved_items(self, store: SQLiteStore):
        """Given an unresolved item created long ago, delete_old_work_items keeps it."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        # Even if old, unresolved items must NOT be deleted
        conn = store._get_connection()
        old_time = datetime.now(timezone.utc) - timedelta(days=365)
        conn.execute(
            "UPDATE work_items SET created_at=? WHERE id=?",
            (old_time.isoformat(), str(wi.id)),
        )
        conn.commit()

        deleted = store.delete_old_work_items(days=30)
        assert deleted == 0
        assert store.get_work_item(wi.id) is not None

    def test_delete_old_returns_count_of_deleted_items(self, store: SQLiteStore):
        """delete_old_work_items returns the number of deleted items."""
        concept = _make_concept()
        store.create_concept(concept)

        old_time = datetime.now(timezone.utc) - timedelta(days=40)
        for _ in range(3):
            wi = _make_work_item(concept.id)
            store.create_work_item(wi)
            conn = store._get_connection()
            conn.execute(
                "UPDATE work_items SET resolved=1, resolved_at=? WHERE id=?",
                (old_time.isoformat(), str(wi.id)),
            )
            conn.commit()

        deleted = store.delete_old_work_items(days=30)
        assert deleted == 3

    def test_delete_old_mixed_items(self, store: SQLiteStore):
        """Given a mix of old/new and resolved/unresolved, only old resolved are deleted."""
        concept = _make_concept()
        store.create_concept(concept)

        old_time = datetime.now(timezone.utc) - timedelta(days=60)

        # Old resolved — should be deleted
        wi_old_resolved = _make_work_item(concept.id, description="old resolved")
        store.create_work_item(wi_old_resolved)
        conn = store._get_connection()
        conn.execute(
            "UPDATE work_items SET resolved=1, resolved_at=? WHERE id=?",
            (old_time.isoformat(), str(wi_old_resolved.id)),
        )
        conn.commit()

        # Recent resolved — should survive
        wi_new_resolved = _make_work_item(concept.id, description="new resolved")
        store.create_work_item(wi_new_resolved)
        store.resolve_work_item(wi_new_resolved.id)

        # Old unresolved — should survive
        wi_old_unresolved = _make_work_item(concept.id, description="old unresolved")
        store.create_work_item(wi_old_unresolved)

        deleted = store.delete_old_work_items(days=30)
        assert deleted == 1
        assert store.get_work_item(wi_old_resolved.id) is None
        assert store.get_work_item(wi_new_resolved.id) is not None
        assert store.get_work_item(wi_old_unresolved.id) is not None


# ---------------------------------------------------------------------------
# AC-8: resolve_work_item sets resolved and resolved_at
# ---------------------------------------------------------------------------

class TestResolveWorkItem:
    """AC-8: resolve_work_item sets resolved=True and stamps resolved_at."""

    def test_resolve_sets_resolved_true(self, store: SQLiteStore):
        """Given an unresolved WorkItem, resolve_work_item sets resolved=True."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        updated = store.resolve_work_item(wi.id)
        assert updated.resolved is True

    def test_resolve_stamps_resolved_at(self, store: SQLiteStore):
        """Given an unresolved WorkItem, resolve_work_item stamps resolved_at."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        before = datetime.now(timezone.utc)
        updated = store.resolve_work_item(wi.id)
        after = datetime.now(timezone.utc)

        assert updated.resolved_at is not None
        assert before <= updated.resolved_at <= after

    def test_resolve_persists_to_store(self, store: SQLiteStore):
        """After resolve_work_item, get_work_item returns resolved=True."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)
        store.resolve_work_item(wi.id)

        retrieved = store.get_work_item(wi.id)
        assert retrieved.resolved is True
        assert retrieved.resolved_at is not None

    def test_resolve_nonexistent_item_raises_key_error(self, store: SQLiteStore):
        """Given a non-existent work item id, resolve_work_item raises KeyError."""
        with pytest.raises(KeyError):
            store.resolve_work_item(uuid.uuid4())

    def test_resolved_items_excluded_from_pending(self, store: SQLiteStore):
        """Resolved items do not appear in get_pending_work_items."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)
        store.resolve_work_item(wi.id)

        pending = store.get_pending_work_items()
        ids = {item.id for item in pending}
        assert wi.id not in ids


# ---------------------------------------------------------------------------
# Work Item CRUD lifecycle
# ---------------------------------------------------------------------------

class TestWorkItemCRUDLifecycle:
    """Work item CRUD operations — create, get, update, delete."""

    def test_create_work_item_persists_and_returns(self, store: SQLiteStore):
        """Given a WorkItem, create_work_item persists and returns it."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)

        result = store.create_work_item(wi)
        assert result.id == wi.id
        retrieved = store.get_work_item(wi.id)
        assert retrieved is not None
        assert retrieved.id == wi.id

    def test_create_duplicate_work_item_raises_value_error(self, store: SQLiteStore):
        """Given a duplicate work item id, create_work_item raises ValueError."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)
        with pytest.raises(ValueError, match="already exists"):
            store.create_work_item(wi)

    def test_get_work_item_returns_none_for_missing(self, store: SQLiteStore):
        """Given a non-existent id, get_work_item returns None."""
        assert store.get_work_item(uuid.uuid4()) is None

    def test_work_item_fields_preserved(self, store: SQLiteStore):
        """All WorkItem fields are preserved through create/get roundtrip."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(
            concept.id,
            item_type="investigate_file",
            description="Investigate this file.",
            file_path="src/parser.py",
            base_priority_score=0.87,
        )
        store.create_work_item(wi)
        retrieved = store.get_work_item(wi.id)

        assert retrieved.item_type == "investigate_file"
        assert retrieved.description == "Investigate this file."
        assert retrieved.file_path == "src/parser.py"
        assert abs(retrieved.base_priority_score - 0.87) < 1e-9
        assert retrieved.failure_count == 0
        assert retrieved.failure_records == []
        assert retrieved.escalated is False
        assert retrieved.resolved is False

    def test_get_pending_work_items_returns_unresolved(self, store: SQLiteStore):
        """get_pending_work_items returns all unresolved work items."""
        concept = _make_concept()
        store.create_concept(concept)
        wi1 = _make_work_item(concept.id, description="pending")
        wi2 = _make_work_item(concept.id, description="will be resolved")
        store.create_work_item(wi1)
        store.create_work_item(wi2)
        store.resolve_work_item(wi2.id)

        pending = store.get_pending_work_items()
        ids = {item.id for item in pending}
        assert wi1.id in ids
        assert wi2.id not in ids

    def test_base_priority_score_index_exists(self, store: SQLiteStore, db_path: Path):
        """Index on base_priority_score DESC exists (technical notes requirement)."""
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_work_items_priority'"
        )
        assert cursor.fetchone() is not None, "Index idx_work_items_priority must exist"
        conn.close()
