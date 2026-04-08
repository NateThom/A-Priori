"""CLI entry points for A-Priori shells."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import uvicorn

from apriori.config import load_config
from apriori.shells.ui.server import create_app
from apriori.storage.dual_writer import DualWriter
from apriori.storage.sqlite_store import SQLiteStore
from apriori.storage.yaml_store import YamlStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apriori")
    subparsers = parser.add_subparsers(dest="command")

    ui = subparsers.add_parser("ui", help="Run the UI API server")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command != "ui":
        parser.print_help()
        return 1

    config = load_config()
    sqlite_store = SQLiteStore(db_path=Path(config.storage.sqlite_path))

    if config.storage.enable_dual_write:
        yaml_store = YamlStore(base_dir=Path(config.storage.yaml_backup_path))
        store = DualWriter(sqlite_store=sqlite_store, yaml_store=yaml_store)
    else:
        store = sqlite_store

    app = create_app(store=store)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
