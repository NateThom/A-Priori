"""Tests for apriori CLI init, search, and status commands (Story 5.1).

Each test traces to a Given/When/Then acceptance criterion from the ticket.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_namespace(**kwargs) -> argparse.Namespace:
    defaults = dict(
        repo=None,
        force=False,
        no_embed=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _make_fake_embedding_service():
    """Return a mock EmbeddingService that never downloads a model.

    ``embed_all`` writes fake zero-vectors via the KnowledgeStore protocol so
    that tests can assert on the concept_embeddings table without loading the
    real sentence-transformers model.
    """
    svc = MagicMock()
    svc.generate_embedding.side_effect = lambda text, **kw: [0.0] * 768

    def _fake_embed_all(store, **kwargs):
        concepts = store.list_concepts()
        for c in concepts:
            store.store_embedding(c.id, [0.0] * 768)
        return len(concepts)

    svc.embed_all.side_effect = _fake_embed_all
    return svc


def _write_py_file(path: Path, content: str = "def hello(): pass\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# AC 1: .apriori/ directory structure is created on first run
# ---------------------------------------------------------------------------


def test_init_creates_apriori_directory(tmp_path: Path, monkeypatch):
    """Given an empty git repo dir, when apriori init is run,
    then .apriori/ is created."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "main.py")

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        args = _make_namespace(repo=str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)

    assert (tmp_path / ".apriori").is_dir()


def test_init_creates_default_config_yaml(tmp_path: Path, monkeypatch):
    """Given an empty repo, when apriori init is run,
    then .apriori/apriori.config.yaml is written with valid YAML."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "main.py")

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        args = _make_namespace(repo=str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)

    config_file = tmp_path / ".apriori" / "apriori.config.yaml"
    assert config_file.exists(), "apriori.config.yaml should exist"
    data = yaml.safe_load(config_file.read_text())
    assert isinstance(data, dict), "config should be a YAML dict"
    # Verify storage section points inside .apriori/
    assert "storage" in data
    assert ".apriori" in data["storage"]["sqlite_path"]


def test_init_creates_sqlite_database(tmp_path: Path, monkeypatch):
    """Given an empty repo, when apriori init is run,
    then a SQLite database is created inside .apriori/."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "main.py")

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        args = _make_namespace(repo=str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)

    db_path = tmp_path / ".apriori" / "graph.db"
    assert db_path.exists(), "SQLite database should be created"
    # Verify schema is set up
    conn = sqlite3.connect(str(db_path))
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "concepts" in tables
    assert "edges" in tables


def test_init_populates_concepts_from_source_files(tmp_path: Path, monkeypatch, capsys):
    """Given a repo with Python files, when apriori init runs,
    then concepts are created and a summary shows concept count > 0."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "greet.py", "def hello():\n    pass\n\ndef goodbye():\n    pass\n")

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        args = _make_namespace(repo=str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)

    captured = capsys.readouterr()
    assert "concept" in captured.out.lower(), f"Expected 'concept' in output: {captured.out}"
    # At least the module + 2 functions should be created
    count_mentions = [w for w in captured.out.split() if w.isdigit() and int(w) >= 2]
    assert count_mentions, f"Expected at least one number >= 2 in summary output: {captured.out}"


def test_init_yaml_concepts_directory_created(tmp_path: Path, monkeypatch):
    """Given an empty repo, when apriori init runs,
    then the YAML concepts backup directory exists."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "app.py")

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        args = _make_namespace(repo=str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)

    assert (tmp_path / ".apriori" / "concepts").is_dir(), "YAML concepts dir should exist"


# ---------------------------------------------------------------------------
# AC 2: Incremental mode — re-init detects existing .apriori/
# ---------------------------------------------------------------------------


def test_init_incremental_mode_does_not_reinitialize_config(tmp_path: Path, monkeypatch):
    """Given init was already run, when apriori init is run again,
    then it detects existing .apriori/ and performs incremental update."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "main.py")

    fake_svc = _make_fake_embedding_service()
    with patch("apriori.embedding.service.EmbeddingService", return_value=fake_svc):
        args = _make_namespace(repo=str(tmp_path))
        monkeypatch.chdir(tmp_path)
        # First init
        cli._cmd_init(args)
        config_mtime_after_first = (tmp_path / ".apriori" / "apriori.config.yaml").stat().st_mtime

        # Add another file
        _write_py_file(tmp_path / "other.py", "def bar(): pass\n")

        # Second init (should be incremental)
        cli._cmd_init(args)

    # Config should NOT have been recreated (mtime unchanged)
    config_mtime_after_second = (tmp_path / ".apriori" / "apriori.config.yaml").stat().st_mtime
    assert config_mtime_after_first == config_mtime_after_second, (
        "Config should not be rewritten on incremental init"
    )


def test_init_incremental_mode_message_printed(tmp_path: Path, monkeypatch, capsys):
    """Given .apriori/ already exists, when apriori init runs,
    then an incremental update message is shown (not a fresh init message)."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "main.py")

    fake_svc = _make_fake_embedding_service()
    with patch("apriori.embedding.service.EmbeddingService", return_value=fake_svc):
        args = _make_namespace(repo=str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)   # first run
        capsys.readouterr()   # discard first run output

        cli._cmd_init(args)   # incremental run
    captured = capsys.readouterr()
    assert "incremental" in captured.out.lower() or "update" in captured.out.lower(), (
        f"Expected incremental update message, got: {captured.out}"
    )


# ---------------------------------------------------------------------------
# AC 3: SQLite fully populated after init
# ---------------------------------------------------------------------------


def test_init_sqlite_fts5_populated(tmp_path: Path, monkeypatch):
    """Given init completes, when the SQLite database is inspected,
    then FTS5 entries exist for the parsed concepts."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "parser.py", "def parse_token(src): pass\n")

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        args = _make_namespace(repo=str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)

    db_path = tmp_path / ".apriori" / "graph.db"
    conn = sqlite3.connect(str(db_path))
    fts_rows = conn.execute("SELECT COUNT(*) FROM concepts_fts").fetchone()[0]
    conn.close()
    assert fts_rows > 0, "FTS5 index should be populated"


def test_init_sqlite_concepts_populated(tmp_path: Path, monkeypatch):
    """Given init completes on a repo with source files,
    all parsed concepts are in SQLite."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "alpha.py", "def alpha(): pass\ndef beta(): pass\n")

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        args = _make_namespace(repo=str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)

    db_path = tmp_path / ".apriori" / "graph.db"
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
    conn.close()
    # module + 2 functions = 3 concepts minimum
    assert count >= 3, f"Expected ≥3 concepts, got {count}"


def test_init_sqlite_embeddings_populated(tmp_path: Path, monkeypatch):
    """AC 7: Given init completes, when the SQLite database is inspected,
    then concept_embeddings rows equal the concept count — fully populated
    and query-ready (arch:no-raw-sql: all writes go via store.store_embedding).

    Uses SQLiteStore (not a raw sqlite3 connection) so that the sqlite_vec
    extension is loaded and the vec0 virtual table is accessible.
    """
    from apriori.shells import cli
    from apriori.storage.sqlite_store import SQLiteStore

    _write_py_file(tmp_path / "worker.py", "def run(): pass\ndef stop(): pass\n")

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        args = _make_namespace(repo=str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)

    db_path = tmp_path / ".apriori" / "graph.db"
    store = SQLiteStore(db_path)
    concept_count = len(store.list_concepts())
    conn = store._get_connection()
    emb_count = conn.execute("SELECT COUNT(*) FROM concept_embeddings").fetchone()[0]

    assert concept_count > 0, "Expected concepts to be created"
    assert emb_count == concept_count, (
        f"concept_embeddings ({emb_count}) should equal concept count ({concept_count})"
    )


# ---------------------------------------------------------------------------
# AC 4: apriori search returns results after init
# ---------------------------------------------------------------------------


def test_search_returns_results_from_populated_store(tmp_path: Path, monkeypatch, capsys):
    """Given init completes, when apriori search 'main' is run,
    then results are printed."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "main.py", "def main(): pass\n")

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        args = _make_namespace(repo=str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)
        capsys.readouterr()

        # Run search
        search_args = argparse.Namespace(query="main", limit=10, db=None)
        cli._cmd_search(search_args)

    captured = capsys.readouterr()
    assert "main" in captured.out.lower(), f"Expected 'main' in search output: {captured.out}"


def test_init_and_search_use_repo_relative_concept_names(tmp_path: Path, monkeypatch, capsys):
    """Given apriori init on a repo, concept names are repo-relative and search
    matches by partial name."""
    from apriori.shells import cli
    from apriori.storage.sqlite_store import SQLiteStore

    _write_py_file(
        tmp_path / "packages" / "cli" / "src" / "lib" / "orchestrator.py",
        "class PipelineOrchestrator:\n    pass\n",
    )

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        args = _make_namespace(repo=str(tmp_path), no_embed=True)
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)
        capsys.readouterr()

        search_args = argparse.Namespace(query="orchestrator", limit=10, db=None, json=False)
        cli._cmd_search(search_args)

    output = capsys.readouterr().out
    assert "packages/cli/src/lib/orchestrator.py::PipelineOrchestrator" in output
    assert str(tmp_path) not in output

    store = SQLiteStore(tmp_path / ".apriori" / "graph.db")
    names = {c.name for c in store.list_concepts()}
    assert "packages/cli/src/lib/orchestrator.py::PipelineOrchestrator" in names
    assert not any(name.startswith(str(tmp_path)) for name in names)


def test_search_no_results_prints_message(tmp_path: Path, monkeypatch, capsys):
    """Given a store with concepts, when searching for a term that matches nothing,
    then a 'no results' message is printed."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "alpha.py", "def alpha(): pass\n")

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        args = _make_namespace(repo=str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)
        capsys.readouterr()

        search_args = argparse.Namespace(query="zzz_no_match_xyz_abc", limit=10, db=None)
        cli._cmd_search(search_args)

    captured = capsys.readouterr()
    assert (
        "no result" in captured.out.lower()
        or "0 result" in captured.out.lower()
        or "found 0" in captured.out.lower()
        or captured.out.strip() == ""
    ), f"Expected empty/no-results output, got: {captured.out}"


# ---------------------------------------------------------------------------
# AC 5: apriori status shows accurate metrics after init
# ---------------------------------------------------------------------------


def test_status_shows_concept_and_edge_counts(tmp_path: Path, monkeypatch, capsys):
    """Given init completes, when apriori status is run,
    then concept and edge counts are reported."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "service.py", "def process(): pass\n")

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        args = _make_namespace(repo=str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)
        capsys.readouterr()

        status_args = argparse.Namespace(db=None)
        cli._cmd_status(status_args)

    captured = capsys.readouterr()
    assert "concept" in captured.out.lower(), f"Expected 'concept' in status output: {captured.out}"


# ---------------------------------------------------------------------------
# AC 6: CLI main() wires subcommands correctly
# ---------------------------------------------------------------------------


def test_main_init_subcommand_registered():
    """Given the CLI is invoked, init is a valid subcommand."""
    from apriori.shells import cli
    import sys

    # Just verify the parser accepts 'init' as a known subcommand.
    # This will raise SystemExit only on --help; we patch sys.argv.
    original = sys.argv
    try:
        sys.argv = ["apriori", "init", "--help"]
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        # --help exits with code 0
        assert exc_info.value.code == 0
    finally:
        sys.argv = original


def test_main_search_subcommand_registered():
    """Given the CLI is invoked, search is a valid subcommand."""
    from apriori.shells import cli
    import sys

    original = sys.argv
    try:
        sys.argv = ["apriori", "search", "--help"]
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 0
    finally:
        sys.argv = original


def test_main_status_subcommand_registered():
    """Given the CLI is invoked, status is a valid subcommand."""
    from apriori.shells import cli
    import sys

    original = sys.argv
    try:
        sys.argv = ["apriori", "status", "--help"]
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 0
    finally:
        sys.argv = original


# ---------------------------------------------------------------------------
# AC 7: No-embed mode skips embedding generation
# ---------------------------------------------------------------------------


def test_init_no_embed_flag_skips_embedding_service(tmp_path: Path, monkeypatch):
    """Given --no-embed is passed, when apriori init runs,
    then EmbeddingService is never instantiated."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "main.py")

    call_count = [0]

    class FakeEmbedding:
        def __init__(self):
            call_count[0] += 1

    with patch("apriori.embedding.service.EmbeddingService", FakeEmbedding):
        args = _make_namespace(repo=str(tmp_path), no_embed=True)
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)

    assert call_count[0] == 0, "EmbeddingService should not be instantiated when --no-embed is set"
