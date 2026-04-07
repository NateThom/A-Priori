"""Tests for SQLiteStore — AC traceability: Story 2.3a.

AC-1: Given a new SQLite database, when the store is initialized, then all
      tables, indexes, and virtual tables (FTS5, vec0) are created with the
      correct schema.
AC-2: Given the database, when WAL mode and foreign keys are checked, then
      both are enabled.
AC-3: Given a Concept object, when create_concept is called, then the concept
      is inserted and the method returns the created Concept with all fields
      populated.
AC-4: Given an existing concept, when update_concept is called with a modified
      description, then the concept's description and updated_at are updated.
AC-5: Given a concept with edges, when delete_concept is called, then the
      concept and all its edges are removed (CASCADE).

DoD coverage: Concept CRUD, Edge CRUD, connection pooling, thread safety.
"""

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apriori.models.concept import Concept, CodeReference
from apriori.models.edge import Edge
from apriori.storage.sqlite_store import SQLiteStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def store(db_path: Path) -> SQLiteStore:
    return SQLiteStore(db_path)


def _make_concept(**kwargs) -> Concept:
    defaults = dict(name="test_concept", description="A test concept.", created_by="agent")
    defaults.update(kwargs)
    return Concept(**defaults)


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
# AC-1: Schema creation
# ---------------------------------------------------------------------------

class TestSchemaCreation:
    """AC-1: all tables, indexes, and virtual tables are created on init."""

    def test_concepts_table_exists(self, store: SQLiteStore, db_path: Path):
        """Given a new SQLite database, when initialized, concepts table exists."""
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='concepts'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_edges_table_exists(self, store: SQLiteStore, db_path: Path):
        """Given a new SQLite database, when initialized, edges table exists."""
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='edges'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_work_items_table_exists(self, store: SQLiteStore, db_path: Path):
        """Given a new SQLite database, when initialized, work_items table exists."""
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='work_items'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_review_outcomes_table_exists(self, store: SQLiteStore, db_path: Path):
        """Given a new SQLite database, when initialized, review_outcomes table exists."""
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='review_outcomes'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_fts5_virtual_table_exists(self, store: SQLiteStore, db_path: Path):
        """Given a new SQLite database, when initialized, FTS5 virtual table exists."""
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='concepts_fts'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_vec0_virtual_table_exists(self, store: SQLiteStore, db_path: Path):
        """Given a new SQLite database, when initialized, vec0 virtual table exists."""
        import sqlite_vec
        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='concept_embeddings'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_edges_unique_constraint_exists(self, store: SQLiteStore, db_path: Path):
        """Edges table has UNIQUE(source_id, target_id, edge_type) constraint."""
        conn = sqlite3.connect(str(db_path))
        # Try inserting duplicate edge directly
        c1_id = str(uuid.uuid4())
        c2_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO concepts (id, name, description, labels, code_references, "
            "created_by, confidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (c1_id, "c1", "desc1", "[]", "[]", "agent", 0.5,
             datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
        )
        conn.execute(
            "INSERT INTO concepts (id, name, description, labels, code_references, "
            "created_by, confidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (c2_id, "c2", "desc2", "[]", "[]", "agent", 0.5,
             datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
        )
        edge_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO edges (id, source_id, target_id, edge_type, evidence_type, "
            "confidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (edge_id, c1_id, c2_id, "depends-on", "semantic", 1.0,
             datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO edges (id, source_id, target_id, edge_type, evidence_type, "
                "confidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), c1_id, c2_id, "depends-on", "semantic", 1.0,
                 datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# AC-2: WAL mode and foreign keys
# ---------------------------------------------------------------------------

class TestDatabaseSettings:
    """AC-2: WAL mode and foreign keys are enabled."""

    def test_wal_mode_enabled(self, store: SQLiteStore, db_path: Path):
        """Given the database, when WAL mode is checked, it is enabled."""
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
        conn.close()

    def test_foreign_keys_enabled(self, store: SQLiteStore):
        """Given the database, when foreign keys are checked, they are enabled."""
        # Use store's own connection to verify FK enforcement
        result = store._execute_scalar("PRAGMA foreign_keys")
        assert result == 1


# ---------------------------------------------------------------------------
# AC-3: create_concept
# ---------------------------------------------------------------------------

class TestCreateConcept:
    """AC-3: create_concept inserts and returns the Concept with all fields."""

    def test_create_concept_returns_concept(self, store: SQLiteStore):
        """Given a Concept, when create_concept is called, returns the Concept."""
        concept = _make_concept()
        result = store.create_concept(concept)
        assert isinstance(result, Concept)
        assert result.id == concept.id

    def test_created_concept_is_retrievable(self, store: SQLiteStore):
        """Given a created concept, get_concept returns it with the same id."""
        concept = _make_concept()
        store.create_concept(concept)
        retrieved = store.get_concept(concept.id)
        assert retrieved is not None
        assert retrieved.id == concept.id

    def test_created_concept_name_preserved(self, store: SQLiteStore):
        """Given a Concept, when created, the name is preserved."""
        concept = _make_concept(name="my_unique_name")
        store.create_concept(concept)
        retrieved = store.get_concept(concept.id)
        assert retrieved.name == "my_unique_name"

    def test_created_concept_description_preserved(self, store: SQLiteStore):
        """Given a Concept, when created, the description is preserved."""
        concept = _make_concept(description="Very specific description.")
        store.create_concept(concept)
        retrieved = store.get_concept(concept.id)
        assert retrieved.description == "Very specific description."

    def test_created_concept_labels_preserved(self, store: SQLiteStore):
        """Given a Concept with labels, when created, labels are preserved."""
        concept = _make_concept(labels={"needs-review", "auto-generated"})
        store.create_concept(concept)
        retrieved = store.get_concept(concept.id)
        assert retrieved.labels == {"needs-review", "auto-generated"}

    def test_created_concept_confidence_preserved(self, store: SQLiteStore):
        """Given a Concept with confidence, when created, confidence is preserved."""
        concept = _make_concept(confidence=0.75)
        store.create_concept(concept)
        retrieved = store.get_concept(concept.id)
        assert abs(retrieved.confidence - 0.75) < 1e-9

    def test_created_concept_code_references_preserved(self, store: SQLiteStore):
        """Given a Concept with code references, when created, references are preserved."""
        ref = CodeReference(
            symbol="parse_fn",
            file_path="src/parser.py",
            content_hash="a" * 64,
            semantic_anchor="Parses source.",
        )
        concept = _make_concept(code_references=[ref])
        store.create_concept(concept)
        retrieved = store.get_concept(concept.id)
        assert len(retrieved.code_references) == 1
        assert retrieved.code_references[0].symbol == "parse_fn"

    def test_create_concept_raises_on_duplicate_id(self, store: SQLiteStore):
        """Given a duplicate concept id, create_concept raises ValueError."""
        concept = _make_concept()
        store.create_concept(concept)
        with pytest.raises(ValueError, match="already exists"):
            store.create_concept(concept)

    def test_get_concept_returns_none_for_missing(self, store: SQLiteStore):
        """Given a non-existent id, get_concept returns None."""
        result = store.get_concept(uuid.uuid4())
        assert result is None

    def test_list_concepts_returns_all(self, store: SQLiteStore):
        """Given multiple concepts, list_concepts returns all of them."""
        c1 = _make_concept(name="alpha")
        c2 = _make_concept(name="beta")
        store.create_concept(c1)
        store.create_concept(c2)
        concepts = store.list_concepts()
        ids = {c.id for c in concepts}
        assert c1.id in ids
        assert c2.id in ids

    def test_list_concepts_filtered_by_labels(self, store: SQLiteStore):
        """Given concepts with different labels, list_concepts filters by label."""
        c1 = _make_concept(name="alpha", labels={"needs-review"})
        c2 = _make_concept(name="beta", labels={"verified"})
        store.create_concept(c1)
        store.create_concept(c2)
        results = store.list_concepts(labels={"needs-review"})
        ids = {c.id for c in results}
        assert c1.id in ids
        assert c2.id not in ids


# ---------------------------------------------------------------------------
# AC-4: update_concept
# ---------------------------------------------------------------------------

class TestUpdateConcept:
    """AC-4: update_concept persists the updated description and updated_at."""

    def test_update_concept_returns_updated_concept(self, store: SQLiteStore):
        """Given an existing concept, update_concept returns the updated Concept."""
        concept = _make_concept()
        store.create_concept(concept)
        updated = concept.model_copy(
            update={"description": "New description.", "updated_at": datetime.now(timezone.utc)}
        )
        result = store.update_concept(updated)
        assert isinstance(result, Concept)
        assert result.description == "New description."

    def test_update_concept_persists_description(self, store: SQLiteStore):
        """Given an updated description, get_concept returns the new description."""
        concept = _make_concept()
        store.create_concept(concept)
        updated = concept.model_copy(
            update={"description": "Updated desc.", "updated_at": datetime.now(timezone.utc)}
        )
        store.update_concept(updated)
        retrieved = store.get_concept(concept.id)
        assert retrieved.description == "Updated desc."

    def test_update_concept_persists_updated_at(self, store: SQLiteStore):
        """Given an updated concept, updated_at reflects the new timestamp."""
        concept = _make_concept()
        store.create_concept(concept)
        new_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        updated = concept.model_copy(update={"updated_at": new_time})
        store.update_concept(updated)
        retrieved = store.get_concept(concept.id)
        assert retrieved.updated_at == new_time

    def test_update_nonexistent_concept_raises_key_error(self, store: SQLiteStore):
        """Given a non-existent concept id, update_concept raises KeyError."""
        ghost = _make_concept()
        with pytest.raises(KeyError):
            store.update_concept(ghost)


# ---------------------------------------------------------------------------
# AC-5: delete_concept with CASCADE
# ---------------------------------------------------------------------------

class TestDeleteConcept:
    """AC-5: delete_concept removes the concept and all its edges (CASCADE)."""

    def test_delete_concept_removes_it(self, store: SQLiteStore):
        """Given an existing concept, delete_concept removes it from the store."""
        concept = _make_concept()
        store.create_concept(concept)
        store.delete_concept(concept.id)
        assert store.get_concept(concept.id) is None

    def test_delete_concept_cascades_to_edges(self, store: SQLiteStore):
        """Given a concept with edges, delete_concept removes the concept and edges."""
        src = _make_concept(name="source")
        tgt = _make_concept(name="target")
        store.create_concept(src)
        store.create_concept(tgt)
        edge = _make_edge(src.id, tgt.id)
        store.create_edge(edge)

        store.delete_concept(src.id)

        assert store.get_concept(src.id) is None
        assert store.get_edge(edge.id) is None

    def test_delete_nonexistent_concept_raises_key_error(self, store: SQLiteStore):
        """Given a non-existent concept id, delete_concept raises KeyError."""
        with pytest.raises(KeyError):
            store.delete_concept(uuid.uuid4())


# ---------------------------------------------------------------------------
# Edge CRUD
# ---------------------------------------------------------------------------

class TestEdgeCRUD:
    """Edge CRUD operations — DoD requirement."""

    def test_create_edge_returns_edge(self, store: SQLiteStore):
        """Given two concepts and an Edge, create_edge returns the Edge."""
        src = _make_concept(name="source")
        tgt = _make_concept(name="target")
        store.create_concept(src)
        store.create_concept(tgt)
        edge = _make_edge(src.id, tgt.id)
        result = store.create_edge(edge)
        assert isinstance(result, Edge)
        assert result.id == edge.id

    def test_get_edge_returns_edge(self, store: SQLiteStore):
        """Given a created edge, get_edge returns it."""
        src = _make_concept(name="source")
        tgt = _make_concept(name="target")
        store.create_concept(src)
        store.create_concept(tgt)
        edge = _make_edge(src.id, tgt.id)
        store.create_edge(edge)
        retrieved = store.get_edge(edge.id)
        assert retrieved is not None
        assert retrieved.id == edge.id

    def test_get_edge_returns_none_for_missing(self, store: SQLiteStore):
        """Given a non-existent edge id, get_edge returns None."""
        assert store.get_edge(uuid.uuid4()) is None

    def test_update_edge_persists_changes(self, store: SQLiteStore):
        """Given an existing edge, update_edge persists the new confidence."""
        src = _make_concept(name="source")
        tgt = _make_concept(name="target")
        store.create_concept(src)
        store.create_concept(tgt)
        edge = _make_edge(src.id, tgt.id)
        store.create_edge(edge)
        updated = edge.model_copy(
            update={"confidence": 0.42, "updated_at": datetime.now(timezone.utc)}
        )
        store.update_edge(updated)
        retrieved = store.get_edge(edge.id)
        assert abs(retrieved.confidence - 0.42) < 1e-9

    def test_update_nonexistent_edge_raises_key_error(self, store: SQLiteStore):
        """Given a non-existent edge id, update_edge raises KeyError."""
        edge = Edge(source_id=uuid.uuid4(), target_id=uuid.uuid4(),
                    edge_type="depends-on", evidence_type="semantic")
        with pytest.raises(KeyError):
            store.update_edge(edge)

    def test_delete_edge_removes_it(self, store: SQLiteStore):
        """Given an existing edge, delete_edge removes it."""
        src = _make_concept(name="source")
        tgt = _make_concept(name="target")
        store.create_concept(src)
        store.create_concept(tgt)
        edge = _make_edge(src.id, tgt.id)
        store.create_edge(edge)
        store.delete_edge(edge.id)
        assert store.get_edge(edge.id) is None

    def test_delete_nonexistent_edge_raises_key_error(self, store: SQLiteStore):
        """Given a non-existent edge id, delete_edge raises KeyError."""
        with pytest.raises(KeyError):
            store.delete_edge(uuid.uuid4())

    def test_create_duplicate_edge_raises_value_error(self, store: SQLiteStore):
        """Given an edge with the same (source, target, type), create_edge raises ValueError."""
        src = _make_concept(name="source")
        tgt = _make_concept(name="target")
        store.create_concept(src)
        store.create_concept(tgt)
        edge1 = _make_edge(src.id, tgt.id)
        store.create_edge(edge1)
        edge2 = _make_edge(src.id, tgt.id)  # same triple, different id
        with pytest.raises(ValueError, match="already exists"):
            store.create_edge(edge2)

    def test_list_edges_by_source(self, store: SQLiteStore):
        """Given multiple edges, list_edges(source_id=...) returns matching edges."""
        c1, c2, c3 = _make_concept(name="c1"), _make_concept(name="c2"), _make_concept(name="c3")
        store.create_concept(c1)
        store.create_concept(c2)
        store.create_concept(c3)
        e1 = _make_edge(c1.id, c2.id)
        e2 = _make_edge(c1.id, c3.id)
        e3 = _make_edge(c2.id, c3.id, edge_type="calls")
        store.create_edge(e1)
        store.create_edge(e2)
        store.create_edge(e3)
        results = store.list_edges(source_id=c1.id)
        result_ids = {e.id for e in results}
        assert e1.id in result_ids
        assert e2.id in result_ids
        assert e3.id not in result_ids

    def test_list_edges_by_edge_type(self, store: SQLiteStore):
        """Given edges of different types, list_edges(edge_type=...) filters correctly."""
        c1, c2, c3 = _make_concept(name="c1"), _make_concept(name="c2"), _make_concept(name="c3")
        store.create_concept(c1)
        store.create_concept(c2)
        store.create_concept(c3)
        e1 = _make_edge(c1.id, c2.id, edge_type="depends-on")
        e2 = _make_edge(c1.id, c3.id, edge_type="calls")
        store.create_edge(e1)
        store.create_edge(e2)
        results = store.list_edges(edge_type="depends-on")
        result_ids = {e.id for e in results}
        assert e1.id in result_ids
        assert e2.id not in result_ids


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    """DoD: thread safety verified — per-thread connections."""

    def test_concurrent_creates_from_multiple_threads(self, store: SQLiteStore):
        """Given concurrent writes from multiple threads, all concepts are created."""
        errors: list[Exception] = []
        created_ids: list[uuid.UUID] = []
        lock = threading.Lock()

        def create_in_thread():
            try:
                concept = _make_concept(name=f"thread_{threading.get_ident()}")
                result = store.create_concept(concept)
                with lock:
                    created_ids.append(result.id)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=create_in_thread) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        assert len(created_ids) == 10

    def test_each_thread_gets_distinct_connection(self, store: SQLiteStore):
        """Given multiple threads, each gets its own connection object."""
        connections: list[int] = []
        lock = threading.Lock()

        def get_conn_id():
            conn = store._get_connection()
            with lock:
                connections.append(id(conn))

        threads = [threading.Thread(target=get_conn_id) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All connection ids should be distinct (each thread has its own)
        assert len(set(connections)) == len(connections)
