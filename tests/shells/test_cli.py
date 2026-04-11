"""Tests for apriori CLI ui command wiring."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from apriori.config import Config
from apriori.shells import cli


class _DummyStore:
    pass


def test_ui_command_constructs_dual_writer_with_expected_kwargs(monkeypatch, tmp_path: Path):
    import apriori.config as config_module
    import apriori.shells.ui.server as server_module
    import apriori.storage.dual_writer as dual_writer_module
    import apriori.storage.sqlite_store as sqlite_store_module
    import apriori.storage.yaml_store as yaml_store_module

    calls: dict[str, object] = {}

    config = Config(
        storage={
            "sqlite_path": str(tmp_path / "db.sqlite3"),
            "yaml_backup_path": str(tmp_path / "backup"),
            "enable_dual_write": True,
        }
    )

    monkeypatch.setattr(config_module, "load_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(sqlite_store_module, "SQLiteStore", lambda db_path: _DummyStore())
    monkeypatch.setattr(yaml_store_module, "YamlStore", lambda base_dir: _DummyStore())

    def _fake_dual_writer(**kwargs):
        calls["kwargs"] = kwargs
        return _DummyStore()

    monkeypatch.setattr(dual_writer_module, "DualWriter", _fake_dual_writer)
    monkeypatch.setattr(server_module, "create_app", lambda *_args: object())

    def _fake_run(app, host, port, reload):
        calls["run"] = {"host": host, "port": port, "reload": reload}

    monkeypatch.setattr("uvicorn.run", _fake_run)

    cli._cmd_ui(argparse.Namespace(host="127.0.0.1", port=8391, db=None, reload=False))

    assert calls["kwargs"].keys() == {"sqlite_store", "yaml_store"}
    assert calls["run"] == {"host": "127.0.0.1", "port": 8391, "reload": False}


def test_ui_command_uses_dot_apriori_config_db_when_no_db_flag(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Given .apriori config, ui command resolves DB from that config when --db is omitted."""
    import apriori.shells.ui.server as server_module
    import apriori.storage.sqlite_store as sqlite_store_module

    monkeypatch.chdir(tmp_path)
    apriori_dir = tmp_path / ".apriori"
    apriori_dir.mkdir()

    (apriori_dir / "apriori.config.yaml").write_text(
        yaml.safe_dump(
            {
                "storage": {
                    "sqlite_path": str(apriori_dir / "graph.db"),
                    "yaml_backup_path": str(apriori_dir / "backup"),
                    "enable_dual_write": False,
                }
            }
        )
    )

    calls: dict[str, object] = {}

    def _fake_sqlite_store(db_path: Path):
        calls["db_path"] = Path(db_path)
        return _DummyStore()

    monkeypatch.setattr(sqlite_store_module, "SQLiteStore", _fake_sqlite_store)
    monkeypatch.setattr(server_module, "create_app", lambda *_args: object())
    monkeypatch.setattr("uvicorn.run", lambda *_args, **_kwargs: None)

    cli._cmd_ui(argparse.Namespace(host="127.0.0.1", port=8391, db=None, reload=False))

    assert calls["db_path"] == apriori_dir / "graph.db"


def test_ui_command_uses_explicit_db_flag_over_config(monkeypatch, tmp_path: Path) -> None:
    """Given explicit --db, ui command uses that path instead of config storage.sqlite_path."""
    import apriori.shells.ui.server as server_module
    import apriori.storage.sqlite_store as sqlite_store_module

    monkeypatch.chdir(tmp_path)
    apriori_dir = tmp_path / ".apriori"
    apriori_dir.mkdir()

    (apriori_dir / "apriori.config.yaml").write_text(
        yaml.safe_dump(
            {
                "storage": {
                    "sqlite_path": str(apriori_dir / "graph.db"),
                    "yaml_backup_path": str(apriori_dir / "backup"),
                    "enable_dual_write": False,
                }
            }
        )
    )

    explicit_db = tmp_path / "custom-graph.db"
    calls: dict[str, object] = {}

    def _fake_sqlite_store(db_path: Path):
        calls["db_path"] = Path(db_path)
        return _DummyStore()

    monkeypatch.setattr(sqlite_store_module, "SQLiteStore", _fake_sqlite_store)
    monkeypatch.setattr(server_module, "create_app", lambda *_args: object())
    monkeypatch.setattr("uvicorn.run", lambda *_args, **_kwargs: None)

    cli._cmd_ui(
        argparse.Namespace(
            host="127.0.0.1",
            port=8391,
            db=str(explicit_db),
            reload=False,
        )
    )

    assert calls["db_path"] == explicit_db
