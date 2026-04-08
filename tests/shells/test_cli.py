"""Tests for apriori CLI ui command wiring."""

from pathlib import Path

from apriori.config import Config
from apriori.shells import cli


class _DummyStore:
    pass


def test_ui_command_constructs_dual_writer_with_expected_kwargs(monkeypatch, tmp_path: Path):
    calls = {}

    config = Config(
        storage={
            "sqlite_path": str(tmp_path / "db.sqlite3"),
            "yaml_backup_path": str(tmp_path / "backup"),
            "enable_dual_write": True,
        }
    )

    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "SQLiteStore", lambda db_path: _DummyStore())
    monkeypatch.setattr(cli, "YamlStore", lambda base_dir: _DummyStore())

    def _fake_dual_writer(**kwargs):
        calls["kwargs"] = kwargs
        return _DummyStore()

    monkeypatch.setattr(cli, "DualWriter", _fake_dual_writer)
    monkeypatch.setattr(cli, "create_app", lambda **kwargs: object())

    def _fake_run(app, host, port):
        calls["run"] = {"host": host, "port": port}

    monkeypatch.setattr(cli.uvicorn, "run", _fake_run)

    rc = cli.main(["ui", "--host", "127.0.0.1", "--port", "8391"])

    assert rc == 0
    assert calls["kwargs"].keys() == {"sqlite_store", "yaml_store"}
    assert calls["run"] == {"host": "127.0.0.1", "port": 8391}
