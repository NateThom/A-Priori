"""Tests for apriori CLI Story 5.2: status, search, rebuild-index, and config commands.

Each test traces to a Given/When/Then acceptance criterion from ticket AP-71.
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_embedding_service():
    """Mock EmbeddingService that never downloads a model."""
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


def _init_repo(tmp_path: Path, monkeypatch) -> None:
    """Run apriori init on tmp_path to set up a populated store."""
    from apriori.shells import cli

    _write_py_file(tmp_path / "service.py", "def process(): pass\ndef validate(): pass\n")
    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        args = argparse.Namespace(repo=str(tmp_path), no_embed=True)
        monkeypatch.chdir(tmp_path)
        cli._cmd_init(args)


# ---------------------------------------------------------------------------
# AC 1: apriori status shows coverage, work queue depth, last parse timestamp
# ---------------------------------------------------------------------------


def test_status_shows_work_queue_depth(tmp_path: Path, monkeypatch, capsys):
    """Given a populated graph, when apriori status is run,
    then the output includes work queue depth as a labeled field."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    capsys.readouterr()

    status_args = argparse.Namespace(db=None, json=False)
    cli._cmd_status(status_args)

    captured = capsys.readouterr()
    # Must show a labeled work queue field (not just the word "work" from the path)
    assert "work queue" in captured.out.lower() or "queue depth" in captured.out.lower(), (
        f"Expected 'work queue' or 'queue depth' label in status output: {captured.out}"
    )


def test_status_shows_last_parse_timestamp(tmp_path: Path, monkeypatch, capsys):
    """Given a populated graph, when apriori status is run,
    then the output includes the last parse timestamp as a labeled field."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    capsys.readouterr()

    status_args = argparse.Namespace(db=None, json=False)
    cli._cmd_status(status_args)

    captured = capsys.readouterr()
    # Must show a labeled timestamp field (not just "last" from the path)
    assert (
        "last parse" in captured.out.lower()
        or "last updated" in captured.out.lower()
        or "last parsed" in captured.out.lower()
    ), f"Expected 'last parse' or 'last updated' label in status output: {captured.out}"


def test_status_shows_coverage_info(tmp_path: Path, monkeypatch, capsys):
    """Given a populated graph, when apriori status is run,
    then the output includes a labeled coverage field."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    capsys.readouterr()

    status_args = argparse.Namespace(db=None, json=False)
    cli._cmd_status(status_args)

    captured = capsys.readouterr()
    # Must show a labeled coverage field (not just the word from the DB path)
    assert "covered files" in captured.out.lower() or "coverage:" in captured.out.lower(), (
        f"Expected 'covered files' or 'coverage:' label in status output: {captured.out}"
    )


def test_status_json_flag_produces_valid_json(tmp_path: Path, monkeypatch, capsys):
    """Given a populated graph, when apriori status --json is run,
    then the output is valid JSON with the expected keys."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    capsys.readouterr()

    status_args = argparse.Namespace(db=None, json=True)
    cli._cmd_status(status_args)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "concepts" in data or "concept_count" in data, (
        f"Expected concept count in JSON: {data}"
    )
    assert "edges" in data or "edge_count" in data, (
        f"Expected edge count in JSON: {data}"
    )


def test_status_json_includes_work_queue_depth(tmp_path: Path, monkeypatch, capsys):
    """Given a populated graph, when apriori status --json is run,
    then the JSON includes work_queue_depth."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    capsys.readouterr()

    status_args = argparse.Namespace(db=None, json=True)
    cli._cmd_status(status_args)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "work_queue_depth" in data, f"Expected work_queue_depth in JSON: {data}"
    assert isinstance(data["work_queue_depth"], int)


def test_status_json_includes_last_parse(tmp_path: Path, monkeypatch, capsys):
    """Given a populated graph, when apriori status --json is run,
    then the JSON includes last_parse timestamp (or None)."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    capsys.readouterr()

    status_args = argparse.Namespace(db=None, json=True)
    cli._cmd_status(status_args)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "last_parse" in data, f"Expected last_parse in JSON: {data}"


# ---------------------------------------------------------------------------
# AC 2: apriori search shows confidence scores
# ---------------------------------------------------------------------------


def test_search_shows_confidence_score(tmp_path: Path, monkeypatch, capsys):
    """Given a populated graph, when apriori search 'process' is run,
    then results include labeled confidence scores."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    capsys.readouterr()

    search_args = argparse.Namespace(query="process", limit=10, db=None, json=False)
    cli._cmd_search(search_args)

    captured = capsys.readouterr()
    assert captured.out.strip(), "Expected non-empty search results"
    # Must show a labeled confidence field (not just "confidence" from the path)
    assert "conf:" in captured.out.lower() or "confidence:" in captured.out.lower(), (
        f"Expected 'conf:' or 'confidence:' label in search output: {captured.out}"
    )


def test_search_json_flag_produces_valid_json(tmp_path: Path, monkeypatch, capsys):
    """Given a populated graph, when apriori search --json is run,
    then the output is valid JSON with results list."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    capsys.readouterr()

    search_args = argparse.Namespace(query="process", limit=10, db=None, json=True)
    cli._cmd_search(search_args)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list), f"Expected JSON list, got: {type(data)}"
    if data:
        item = data[0]
        assert "name" in item, f"Expected 'name' in search result: {item}"
        assert "confidence" in item, f"Expected 'confidence' in search result: {item}"


def test_search_json_no_results_returns_empty_list(tmp_path: Path, monkeypatch, capsys):
    """Given a populated graph, when apriori search --json finds no matches,
    then the output is an empty JSON list."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    capsys.readouterr()

    search_args = argparse.Namespace(
        query="zzz_absolutely_no_match_xyz", limit=10, db=None, json=True
    )
    cli._cmd_search(search_args)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == [], f"Expected empty list for no results, got: {data}"


# ---------------------------------------------------------------------------
# AC 3: apriori rebuild-index reconstructs SQLite from YAML
# ---------------------------------------------------------------------------


def test_rebuild_index_recreates_sqlite_from_yaml(tmp_path: Path, monkeypatch, capsys):
    """Given YAML files exist but SQLite is missing, when apriori rebuild-index is run,
    then the SQLite database is reconstructed from YAML files."""
    import sqlite3

    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)

    db_path = tmp_path / ".apriori" / "graph.db"
    assert db_path.exists(), "DB should exist after init"

    # Remove SQLite so we can test rebuild
    db_path.unlink()
    assert not db_path.exists(), "DB should be removed"

    capsys.readouterr()

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        rebuild_args = argparse.Namespace(db=None, yaml_path=None, no_embed=False)
        cli._cmd_rebuild_index(rebuild_args)

    # DB should now exist again
    assert db_path.exists(), "SQLite should be reconstructed after rebuild-index"

    # Verify it has concepts
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
    conn.close()
    assert count > 0, f"Expected concepts after rebuild, got {count}"


def test_rebuild_index_prints_success_message(tmp_path: Path, monkeypatch, capsys):
    """Given YAML files exist, when apriori rebuild-index is run,
    then a success message is displayed."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    db_path = tmp_path / ".apriori" / "graph.db"
    db_path.unlink()
    capsys.readouterr()

    with patch("apriori.embedding.service.EmbeddingService", return_value=_make_fake_embedding_service()):
        rebuild_args = argparse.Namespace(db=None, yaml_path=None, no_embed=False)
        cli._cmd_rebuild_index(rebuild_args)

    captured = capsys.readouterr()
    assert (
        "rebuild" in captured.out.lower()
        or "complete" in captured.out.lower()
        or "success" in captured.out.lower()
    ), f"Expected success message in rebuild output: {captured.out}"


def test_rebuild_index_subcommand_registered():
    """Given the CLI is invoked, rebuild-index is a valid subcommand."""
    import sys

    from apriori.shells import cli

    original = sys.argv
    try:
        sys.argv = ["apriori", "rebuild-index", "--help"]
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 0
    finally:
        sys.argv = original


# ---------------------------------------------------------------------------
# AC 4: apriori config prints current configuration
# ---------------------------------------------------------------------------


def test_config_prints_effective_values(tmp_path: Path, monkeypatch, capsys):
    """Given no arguments, when apriori config is run,
    then the current configuration is printed with all effective values."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    capsys.readouterr()

    config_args = argparse.Namespace(config_subcommand=None, json=False)
    cli._cmd_config(config_args)

    captured = capsys.readouterr()
    # Should show key config sections
    assert "storage" in captured.out.lower() or "sqlite" in captured.out.lower(), (
        f"Expected storage config in output: {captured.out}"
    )
    assert "librarian" in captured.out.lower() or "embedding" in captured.out.lower(), (
        f"Expected librarian or embedding config in output: {captured.out}"
    )


def test_config_json_flag_produces_valid_json(tmp_path: Path, monkeypatch, capsys):
    """Given no arguments, when apriori config --json is run,
    then the output is valid JSON with all config sections."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    capsys.readouterr()

    config_args = argparse.Namespace(config_subcommand=None, json=True)
    cli._cmd_config(config_args)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "storage" in data, f"Expected 'storage' key in config JSON: {data}"
    assert "librarian" in data, f"Expected 'librarian' key in config JSON: {data}"


# ---------------------------------------------------------------------------
# AC 5: apriori config set updates the config file
# ---------------------------------------------------------------------------


def test_config_set_updates_config_file(tmp_path: Path, monkeypatch, capsys):
    """Given a key-value pair, when apriori config set librarian.max_iterations_per_run 50 is run,
    then the config file is updated with the new value."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    capsys.readouterr()

    config_set_args = argparse.Namespace(
        config_subcommand="set",
        key="librarian.max_iterations_per_run",
        value="50",
        json=False,
    )
    cli._cmd_config(config_set_args)

    # Read back and verify
    config_path = tmp_path / ".apriori" / "apriori.config.yaml"
    data = yaml.safe_load(config_path.read_text())
    assert data.get("librarian", {}).get("max_iterations_per_run") == 50, (
        f"Expected librarian.max_iterations_per_run=50 in config, got: {data}"
    )


def test_config_set_prints_confirmation(tmp_path: Path, monkeypatch, capsys):
    """Given apriori config set is run with valid key/value,
    then a confirmation message is printed."""
    from apriori.shells import cli

    _init_repo(tmp_path, monkeypatch)
    capsys.readouterr()

    config_set_args = argparse.Namespace(
        config_subcommand="set",
        key="librarian.max_iterations_per_run",
        value="20",
        json=False,
    )
    cli._cmd_config(config_set_args)

    captured = capsys.readouterr()
    assert captured.out.strip(), "Expected confirmation output after config set"


def test_config_subcommand_registered():
    """Given the CLI is invoked, config is a valid subcommand."""
    import sys

    from apriori.shells import cli

    original = sys.argv
    try:
        sys.argv = ["apriori", "config", "--help"]
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 0
    finally:
        sys.argv = original
