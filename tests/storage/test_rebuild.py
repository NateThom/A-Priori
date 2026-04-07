"""Tests for rebuild_index_from_yaml — AC traceability: Story 2.8.

AC:
- AC1: Given concept and edge YAML files, when rebuild_index_from_yaml is run,
  then a new SQLite database is created with all concepts, edges, embeddings,
  and FTS5 entries matching the YAML data.
- AC2: Given the rebuilt database, when any query is run, then results match
  what was in the YAML files exactly.
- AC3: Given rebuild_index_from_yaml is run twice consecutively, when the second
  run completes, then the database state is identical to after the first run
  (idempotent).
- AC4: Given 1,000 concept YAML files, when rebuild_index_from_yaml is run,
  then it completes within 60 seconds including embedding regeneration.
- AC5: Given rebuild_index_from_yaml is invoked, when it runs, then it reports
  progress.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.storage.rebuild import rebuild_index_from_yaml
from apriori.storage.sqlite_store import SQLiteStore
from apriori.storage.yaml_store import YamlStore


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


_EMBEDDING_DIMS = 768  # matches SQLiteStore._EMBEDDING_DIMS


def _make_mock_embedding_service() -> MagicMock:
    """Return an EmbeddingService mock that returns deterministic 768-dim vectors.

    Only ``generate_embedding`` is configured — no ``generate_embeddings_batch``
    — so that the rebuild fallback path (individual calls) is exercised and
    ``generate_embedding.call_count`` accurately reflects total embeddings made.
    """
    svc = MagicMock(spec=["generate_embedding"])

    def _generate(text: str, text_type: str = "passage") -> list[float]:
        # Deterministic non-zero vector based on text content.
        seed = hash(text) % (2**31)
        return [(seed ^ (i * 7919)) % 1000 / 1000.0 for i in range(_EMBEDDING_DIMS)]

    svc.generate_embedding.side_effect = _generate
    return svc


def _make_concept(name: str, description: str = "") -> Concept:
    return Concept(
        name=name,
        description=description or f"Description of {name}.",
        created_by="agent",
    )


def _make_edge(source_id: uuid.UUID, target_id: uuid.UUID) -> Edge:
    return Edge(
        source_id=source_id,
        target_id=target_id,
        edge_type="depends-on",
        evidence_type="semantic",
    )


@pytest.fixture
def yaml_dir(tmp_path: Path) -> Path:
    d = tmp_path / "yaml"
    d.mkdir()
    return d


@pytest.fixture
def yaml_store(yaml_dir: Path) -> YamlStore:
    return YamlStore(base_dir=yaml_dir)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "knowledge.db"


@pytest.fixture
def embedding_service() -> MagicMock:
    return _make_mock_embedding_service()


# ---------------------------------------------------------------------------
# AC1: New SQLite DB contains all concepts, edges, embeddings, FTS5 entries
# ---------------------------------------------------------------------------


class TestRebuildCreatesDatabase:
    """AC1: rebuild_index_from_yaml populates a fresh SQLite DB from YAML files."""

    def test_concepts_in_yaml_appear_in_rebuilt_db(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        # Given: two concepts written to YAML
        c1 = _make_concept("Alpha")
        c2 = _make_concept("Beta")
        yaml_store.write_concept(c1)
        yaml_store.write_concept(c2)

        # When
        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)

        # Then: both concepts in SQLite
        store = SQLiteStore(db_path)
        assert store.get_concept(c1.id) is not None
        assert store.get_concept(c2.id) is not None

    def test_edges_in_yaml_appear_in_rebuilt_db(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        # Given: two concepts + one edge
        c1 = _make_concept("Source")
        c2 = _make_concept("Target")
        yaml_store.write_concept(c1)
        yaml_store.write_concept(c2)
        edge = _make_edge(c1.id, c2.id)
        yaml_store.write_edge(edge)

        # When
        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)

        # Then: edge in SQLite
        store = SQLiteStore(db_path)
        result = store.get_edge(edge.id)
        assert result is not None
        assert result.source_id == c1.id
        assert result.target_id == c2.id

    def test_embeddings_generated_for_all_concepts(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        # Given: three concepts in YAML
        for i in range(3):
            yaml_store.write_concept(_make_concept(f"Concept{i}"))

        # When
        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)

        # Then: embedding service called for all concepts
        assert embedding_service.generate_embedding.call_count == 3

    def test_fts5_index_populated(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        # Given: concept written to YAML
        c = _make_concept("UniqueSearchTerm", description="A very unique description.")
        yaml_store.write_concept(c)

        # When
        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)

        # Then: FTS5 search finds it
        store = SQLiteStore(db_path)
        results = store.search_keyword("UniqueSearchTerm")
        assert any(r.id == c.id for r in results)

    def test_empty_yaml_store_creates_empty_db(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        # Given: no YAML files
        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)

        store = SQLiteStore(db_path)
        assert store.list_concepts() == []
        assert store.list_edges() == []


# ---------------------------------------------------------------------------
# AC2: Query results match YAML data exactly
# ---------------------------------------------------------------------------


class TestRebuildQueryAccuracy:
    """AC2: Rebuilt DB query results match the original YAML content."""

    def test_concept_fields_match_yaml(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        # Given: concept with specific fields written to YAML
        original = Concept(
            name="Precise Concept",
            description="A precisely described concept.",
            created_by="agent",
            labels={"tag-a", "tag-b"},
            confidence=0.9,
        )
        yaml_store.write_concept(original)

        # When
        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)

        # Then: retrieved concept matches original
        store = SQLiteStore(db_path)
        result = store.get_concept(original.id)
        assert result is not None
        assert result.id == original.id
        assert result.name == original.name
        assert result.description == original.description
        assert result.labels == original.labels
        assert abs(result.confidence - original.confidence) < 1e-6

    def test_edge_fields_match_yaml(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        c1 = _make_concept("Src")
        c2 = _make_concept("Tgt")
        yaml_store.write_concept(c1)
        yaml_store.write_concept(c2)
        original_edge = Edge(
            source_id=c1.id,
            target_id=c2.id,
            edge_type="causes",
            evidence_type="semantic",
            confidence=0.75,
        )
        yaml_store.write_edge(original_edge)

        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)

        store = SQLiteStore(db_path)
        result = store.get_edge(original_edge.id)
        assert result is not None
        assert result.edge_type == "causes"
        assert abs(result.confidence - 0.75) < 1e-6

    def test_all_concepts_listed_after_rebuild(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        names = ["Alpha", "Beta", "Gamma", "Delta"]
        concept_ids = set()
        for name in names:
            c = _make_concept(name)
            yaml_store.write_concept(c)
            concept_ids.add(c.id)

        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)

        store = SQLiteStore(db_path)
        results = store.list_concepts()
        assert len(results) == len(names)
        assert {c.id for c in results} == concept_ids


# ---------------------------------------------------------------------------
# AC3: Idempotent — running twice produces identical state
# ---------------------------------------------------------------------------


class TestRebuildIdempotency:
    """AC3: Running rebuild_index_from_yaml twice gives identical DB state."""

    def test_second_run_same_concept_count(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        for i in range(5):
            yaml_store.write_concept(_make_concept(f"Concept{i}"))

        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)
        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)

        store = SQLiteStore(db_path)
        assert len(store.list_concepts()) == 5

    def test_second_run_same_edge_count(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        concepts = []
        for i in range(3):
            c = _make_concept(f"C{i}")
            yaml_store.write_concept(c)
            concepts.append(c)
        edge = _make_edge(concepts[0].id, concepts[1].id)
        yaml_store.write_edge(edge)

        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)
        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)

        store = SQLiteStore(db_path)
        assert len(store.list_edges()) == 1

    def test_second_run_identical_concept_data(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        c = _make_concept("Idempotent Concept")
        yaml_store.write_concept(c)

        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)
        store_first = SQLiteStore(db_path)
        first_result = store_first.get_concept(c.id)

        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)
        store_second = SQLiteStore(db_path)
        second_result = store_second.get_concept(c.id)

        assert first_result is not None
        assert second_result is not None
        assert first_result.name == second_result.name
        assert first_result.description == second_result.description


# ---------------------------------------------------------------------------
# AC4: Performance — 1000 concepts in <60 seconds
# ---------------------------------------------------------------------------


class TestRebuildPerformance:
    """AC4: rebuild_index_from_yaml handles 1000 concepts in under 60 seconds."""

    def test_one_thousand_concepts_within_60_seconds(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        # Given: 1000 concept YAML files
        for i in range(1000):
            yaml_store.write_concept(_make_concept(f"Concept{i:04d}"))

        # When
        start = time.monotonic()
        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)
        elapsed = time.monotonic() - start

        # Then: completes within 60 seconds
        assert elapsed < 60.0, f"rebuild_index_from_yaml took {elapsed:.1f}s for 1000 concepts"

        # And: all 1000 concepts in SQLite
        store = SQLiteStore(db_path)
        assert len(store.list_concepts()) == 1000


# ---------------------------------------------------------------------------
# AC5: Progress reporting
# ---------------------------------------------------------------------------


class TestRebuildProgressReporting:
    """AC5: rebuild_index_from_yaml calls progress_callback during execution."""

    def test_progress_callback_called(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        for i in range(3):
            yaml_store.write_concept(_make_concept(f"Concept{i}"))

        calls: list[tuple[int, int, str]] = []

        def progress(current: int, total: int, message: str) -> None:
            calls.append((current, total, message))

        rebuild_index_from_yaml(
            yaml_store, db_path, embedding_service, progress_callback=progress
        )

        assert len(calls) > 0, "progress_callback was never called"

    def test_progress_callback_reports_total_count(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        n = 5
        for i in range(n):
            yaml_store.write_concept(_make_concept(f"C{i}"))

        totals: list[int] = []

        def progress(current: int, total: int, message: str) -> None:
            totals.append(total)

        rebuild_index_from_yaml(
            yaml_store, db_path, embedding_service, progress_callback=progress
        )

        # At least one call should report the correct total concept count
        assert any(t == n for t in totals), (
            f"Expected total={n} in progress calls; got totals={totals}"
        )

    def test_progress_callback_not_required(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        yaml_store.write_concept(_make_concept("NoCallback"))

        # Should not raise when progress_callback is None (the default)
        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)

        store = SQLiteStore(db_path)
        assert len(store.list_concepts()) == 1


# ---------------------------------------------------------------------------
# Atomic swap
# ---------------------------------------------------------------------------


class TestAtomicSwap:
    """Rebuild creates a new DB file and swaps it in atomically."""

    def test_existing_db_replaced_after_rebuild(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        # Given: an existing DB with stale data
        stale_concept = _make_concept("StaleData")
        stale_store = SQLiteStore(db_path)
        stale_store.create_concept(stale_concept)

        # And: YAML has different (authoritative) data
        fresh_concept = _make_concept("FreshData")
        yaml_store.write_concept(fresh_concept)

        # When: rebuild runs
        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)

        # Then: the rebuilt DB contains only YAML data (stale data is gone)
        result_store = SQLiteStore(db_path)
        assert result_store.get_concept(stale_concept.id) is None
        assert result_store.get_concept(fresh_concept.id) is not None

    def test_db_file_exists_after_rebuild(
        self, yaml_store: YamlStore, db_path: Path, embedding_service: MagicMock
    ) -> None:
        yaml_store.write_concept(_make_concept("Post-rebuild"))

        rebuild_index_from_yaml(yaml_store, db_path, embedding_service)

        assert db_path.exists()
