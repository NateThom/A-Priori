"""Tests for DualWriter — AC traceability: Story 2.7.

AC:
- AC1: Given a concept is created through the dual writer, when the operation
  completes, then the concept exists in both SQLite and YAML.
- AC2: Given a concept is updated through the dual writer, when the operation
  completes, then both stores reflect the update.
- AC3: Given a SQLite write failure (simulated), when a concept is created,
  then the YAML write succeeds, a warning is logged, and the method does not
  raise an exception.
- AC4: Given a work item is created through the dual writer, when the operation
  completes, then it exists only in SQLite.
- AC5: Given a review outcome is recorded, when the operation completes, then
  it exists only in SQLite.
- AC6: Given all reads, when any query method is called, then it is served
  from SQLite.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.models.review_outcome import ReviewOutcome
from apriori.models.work_item import WorkItem
from apriori.storage.dual_writer import DualWriter
from apriori.storage.sqlite_store import SQLiteStore
from apriori.storage.yaml_store import YamlStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def yaml_dir(tmp_path: Path) -> Path:
    d = tmp_path / "yaml"
    d.mkdir()
    return d


@pytest.fixture
def sqlite_store(db_path: Path) -> SQLiteStore:
    return SQLiteStore(db_path)


@pytest.fixture
def yaml_store(yaml_dir: Path) -> YamlStore:
    return YamlStore(base_dir=yaml_dir)


@pytest.fixture
def dual(sqlite_store: SQLiteStore, yaml_store: YamlStore) -> DualWriter:
    return DualWriter(sqlite_store=sqlite_store, yaml_store=yaml_store)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_concept(name: str = "test_concept") -> Concept:
    return Concept(name=name, description="A test concept.", created_by="agent")


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
        description="Needs verification.",
    )


def _make_review_outcome(concept_id: uuid.UUID) -> ReviewOutcome:
    return ReviewOutcome(
        concept_id=concept_id,
        action="verified",
        reviewer="agent",
    )


# ---------------------------------------------------------------------------
# AC1: Concept create writes to both stores
# ---------------------------------------------------------------------------


class TestConceptCreateDualWrite:
    """AC1: Concept created through dual writer exists in both SQLite and YAML."""

    def test_concept_exists_in_sqlite_after_create(
        self, dual: DualWriter, sqlite_store: SQLiteStore
    ) -> None:
        concept = _make_concept()
        created = dual.create_concept(concept)
        result = sqlite_store.get_concept(created.id)
        assert result is not None
        assert result.name == concept.name

    def test_concept_exists_in_yaml_after_create(
        self, dual: DualWriter, yaml_store: YamlStore
    ) -> None:
        concept = _make_concept()
        created = dual.create_concept(concept)
        result = yaml_store.read_concept(created.id)
        assert result is not None
        assert result.name == concept.name

    def test_create_concept_returns_concept(self, dual: DualWriter) -> None:
        concept = _make_concept()
        created = dual.create_concept(concept)
        assert created.id == concept.id
        assert created.name == concept.name

    def test_create_duplicate_concept_raises_value_error(
        self, dual: DualWriter
    ) -> None:
        concept = _make_concept()
        dual.create_concept(concept)
        with pytest.raises(ValueError):
            dual.create_concept(concept)


# ---------------------------------------------------------------------------
# AC2: Concept update writes to both stores
# ---------------------------------------------------------------------------


class TestConceptUpdateDualWrite:
    """AC2: Concept updated through dual writer reflected in both stores."""

    def test_update_reflects_in_sqlite(
        self, dual: DualWriter, sqlite_store: SQLiteStore
    ) -> None:
        concept = dual.create_concept(_make_concept())
        updated = concept.model_copy(update={"description": "Updated description."})
        dual.update_concept(updated)
        result = sqlite_store.get_concept(concept.id)
        assert result is not None
        assert result.description == "Updated description."

    def test_update_reflects_in_yaml(
        self, dual: DualWriter, yaml_store: YamlStore
    ) -> None:
        concept = dual.create_concept(_make_concept())
        updated = concept.model_copy(update={"description": "Updated description."})
        dual.update_concept(updated)
        result = yaml_store.read_concept(concept.id)
        assert result is not None
        assert result.description == "Updated description."

    def test_update_nonexistent_concept_raises_key_error(
        self, dual: DualWriter
    ) -> None:
        fake = _make_concept()
        with pytest.raises(KeyError):
            dual.update_concept(fake)

    def test_delete_removes_from_both_stores(
        self, dual: DualWriter, sqlite_store: SQLiteStore, yaml_store: YamlStore
    ) -> None:
        concept = dual.create_concept(_make_concept())
        dual.delete_concept(concept.id)
        assert sqlite_store.get_concept(concept.id) is None
        assert yaml_store.read_concept(concept.id) is None


# ---------------------------------------------------------------------------
# AC3: SQLite failure tolerance for concept create
# ---------------------------------------------------------------------------


class TestSQLiteFailureTolerance:
    """AC3: SQLite failure leaves YAML intact, logs warning, does not raise."""

    def test_yaml_written_when_sqlite_fails_on_create(
        self, dual: DualWriter, sqlite_store: SQLiteStore, yaml_store: YamlStore, caplog
    ) -> None:
        concept = _make_concept()
        with patch.object(
            sqlite_store, "create_concept", side_effect=Exception("DB error")
        ):
            with caplog.at_level(logging.WARNING, logger="apriori.storage.dual_writer"):
                result = dual.create_concept(concept)
        # YAML was written (authoritative store succeeded)
        yaml_concept = yaml_store.read_concept(concept.id)
        assert yaml_concept is not None
        assert yaml_concept.name == concept.name

    def test_warning_logged_when_sqlite_fails_on_create(
        self, dual: DualWriter, sqlite_store: SQLiteStore, caplog
    ) -> None:
        concept = _make_concept()
        with patch.object(
            sqlite_store, "create_concept", side_effect=Exception("DB error")
        ):
            with caplog.at_level(logging.WARNING, logger="apriori.storage.dual_writer"):
                dual.create_concept(concept)
        assert any("SQLite" in r.message or "sqlite" in r.message.lower() for r in caplog.records)

    def test_no_exception_raised_when_sqlite_fails_on_create(
        self, dual: DualWriter, sqlite_store: SQLiteStore
    ) -> None:
        concept = _make_concept()
        with patch.object(
            sqlite_store, "create_concept", side_effect=Exception("DB error")
        ):
            # Must NOT raise
            result = dual.create_concept(concept)
        assert result.id == concept.id

    def test_yaml_failure_propagates(
        self, dual: DualWriter, yaml_store: YamlStore
    ) -> None:
        concept = _make_concept()
        with patch.object(
            yaml_store, "write_concept", side_effect=Exception("YAML error")
        ):
            with pytest.raises(Exception, match="YAML error"):
                dual.create_concept(concept)

    def test_sqlite_failure_on_update_is_tolerated(
        self, dual: DualWriter, sqlite_store: SQLiteStore, yaml_store: YamlStore, caplog
    ) -> None:
        concept = dual.create_concept(_make_concept())
        updated = concept.model_copy(update={"description": "New desc."})
        with patch.object(
            sqlite_store, "update_concept", side_effect=Exception("DB error")
        ):
            with caplog.at_level(logging.WARNING, logger="apriori.storage.dual_writer"):
                dual.update_concept(updated)
        # YAML should still be updated
        yaml_result = yaml_store.read_concept(concept.id)
        assert yaml_result is not None
        assert yaml_result.description == "New desc."


# ---------------------------------------------------------------------------
# AC4: Work item is SQLite-only
# ---------------------------------------------------------------------------


class TestWorkItemSQLiteOnly:
    """AC4: Work item created through dual writer exists only in SQLite."""

    def test_work_item_exists_in_sqlite(
        self, dual: DualWriter, sqlite_store: SQLiteStore
    ) -> None:
        concept = dual.create_concept(_make_concept())
        wi = _make_work_item(concept.id)
        created = dual.create_work_item(wi)
        result = sqlite_store.get_work_item(created.id)
        assert result is not None

    def test_work_item_not_in_yaml(
        self, dual: DualWriter, yaml_store: YamlStore
    ) -> None:
        concept = dual.create_concept(_make_concept())
        wi = _make_work_item(concept.id)
        dual.create_work_item(wi)
        # YamlStore has no list API; verify by checking concept files not polluted
        # (no work item file should exist in yaml_store concepts/ or edges/ dirs)
        concepts_dir = yaml_store._concepts_dir
        edges_dir = yaml_store._edges_dir
        all_yaml_files = list(concepts_dir.glob("*.yaml")) + list(edges_dir.glob("*.yaml"))
        yaml_ids = set()
        import yaml as _yaml
        for f in all_yaml_files:
            data = _yaml.safe_load(f.read_text())
            if data and "id" in data:
                yaml_ids.add(str(data["id"]))
        assert str(wi.id) not in yaml_ids


# ---------------------------------------------------------------------------
# AC5: Review outcome is SQLite-only
# ---------------------------------------------------------------------------


class TestReviewOutcomeSQLiteOnly:
    """AC5: Review outcome recorded through dual writer exists only in SQLite."""

    def test_review_outcome_exists_in_sqlite(
        self, dual: DualWriter, sqlite_store: SQLiteStore
    ) -> None:
        concept = dual.create_concept(_make_concept())
        outcome = _make_review_outcome(concept.id)
        dual.create_review_outcome(outcome)
        results = sqlite_store.get_review_outcomes_for_concept(concept.id)
        assert len(results) == 1

    def test_review_outcome_not_in_yaml_concepts_or_edges(
        self, dual: DualWriter, yaml_store: YamlStore
    ) -> None:
        concept = dual.create_concept(_make_concept())
        outcome = _make_review_outcome(concept.id)
        dual.create_review_outcome(outcome)
        # Only the concept file should exist in YAML
        concepts_dir = yaml_store._concepts_dir
        edges_dir = yaml_store._edges_dir
        assert len(list(edges_dir.glob("*.yaml"))) == 0


# ---------------------------------------------------------------------------
# AC6: All reads delegated to SQLite
# ---------------------------------------------------------------------------


class TestReadsDelegatedToSQLite:
    """AC6: Query methods are served from SQLite."""

    def test_get_concept_reads_from_sqlite(
        self, dual: DualWriter, yaml_store: YamlStore
    ) -> None:
        # Write concept through dual writer, then verify get_concept reads SQLite
        concept = dual.create_concept(_make_concept("read-test"))
        # Corrupt the YAML to ensure reads come from SQLite
        yaml_store.write_concept(
            concept.model_copy(update={"description": "YAML-ONLY-VALUE"})
        )
        result = dual.get_concept(concept.id)
        assert result is not None
        assert result.description != "YAML-ONLY-VALUE"

    def test_list_concepts_served_from_sqlite(
        self, dual: DualWriter
    ) -> None:
        dual.create_concept(_make_concept("concept-a"))
        dual.create_concept(_make_concept("concept-b"))
        result = dual.list_concepts()
        assert len(result) == 2

    def test_get_nonexistent_concept_returns_none(self, dual: DualWriter) -> None:
        assert dual.get_concept(uuid.uuid4()) is None

    def test_list_edges_served_from_sqlite(self, dual: DualWriter) -> None:
        src = dual.create_concept(_make_concept("src"))
        tgt = dual.create_concept(_make_concept("tgt"))
        edge = _make_edge(src.id, tgt.id)
        dual.create_edge(edge)
        results = dual.list_edges(source_id=src.id)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Edge dual-write
# ---------------------------------------------------------------------------


class TestEdgeDualWrite:
    """Edges are written to both stores (same coordination as Concepts)."""

    def test_edge_create_writes_to_sqlite_and_yaml(
        self, dual: DualWriter, sqlite_store: SQLiteStore, yaml_store: YamlStore
    ) -> None:
        src = dual.create_concept(_make_concept("src"))
        tgt = dual.create_concept(_make_concept("tgt"))
        edge = _make_edge(src.id, tgt.id)
        created = dual.create_edge(edge)
        # SQLite
        assert sqlite_store.get_edge(created.id) is not None
        # YAML
        assert yaml_store.read_edge(created.id) is not None

    def test_edge_delete_removes_from_both_stores(
        self, dual: DualWriter, sqlite_store: SQLiteStore, yaml_store: YamlStore
    ) -> None:
        src = dual.create_concept(_make_concept("src"))
        tgt = dual.create_concept(_make_concept("tgt"))
        edge = dual.create_edge(_make_edge(src.id, tgt.id))
        dual.delete_edge(edge.id)
        assert sqlite_store.get_edge(edge.id) is None
        assert yaml_store.read_edge(edge.id) is None

    def test_sqlite_failure_on_edge_create_is_tolerated(
        self, dual: DualWriter, sqlite_store: SQLiteStore, yaml_store: YamlStore, caplog
    ) -> None:
        src = dual.create_concept(_make_concept("src"))
        tgt = dual.create_concept(_make_concept("tgt"))
        edge = _make_edge(src.id, tgt.id)
        with patch.object(
            sqlite_store, "create_edge", side_effect=Exception("DB error")
        ):
            with caplog.at_level(logging.WARNING, logger="apriori.storage.dual_writer"):
                dual.create_edge(edge)
        # YAML has the edge
        assert yaml_store.read_edge(edge.id) is not None
