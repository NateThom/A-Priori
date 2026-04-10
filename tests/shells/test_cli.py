"""Tests for apriori CLI ui command wiring."""

from __future__ import annotations

import argparse
from pathlib import Path

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

    monkeypatch.setattr(config_module, "load_config", lambda: config)
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
