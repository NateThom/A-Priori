"""A-Priori CLI entry point (arch:core-lib-thin-shells).

Usage::

    apriori ui [--host HOST] [--port PORT] [--db PATH] [--reload]

The ``ui`` subcommand launches the FastAPI server backed by the SQLite store
specified by ``--db`` (default: value from apriori.config.yaml or ``./apriori.db``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _cmd_ui(args: argparse.Namespace) -> None:
    """Start the read-only Graph API server."""
    try:
        import uvicorn
    except ImportError:
        print(
            "Error: uvicorn is required to run the UI server.\n"
            "Install it with: pip install uvicorn",
            file=sys.stderr,
        )
        sys.exit(1)

    from apriori.config import load_config
    from apriori.shells.ui.server import create_app
    from apriori.storage.dual_writer import DualWriter
    from apriori.storage.sqlite_store import SQLiteStore
    from apriori.storage.yaml_store import YamlStore

    config = load_config()

    db_path = Path(args.db) if args.db else Path(config.storage.sqlite_path)
    yaml_path = Path(config.storage.yaml_backup_path)

    sqlite_store = SQLiteStore(db_path)
    if config.storage.enable_dual_write:
        yaml_store = YamlStore(yaml_path)
        store = DualWriter(sqlite_store=sqlite_store, yaml_store=yaml_store)
    else:
        store = sqlite_store  # type: ignore[assignment]

    app = create_app(store, config)

    print(f"Starting A-Priori UI server on http://{args.host}:{args.port}")
    print(f"Database: {db_path.resolve()}")
    print("API docs: http://{}:{}/docs".format(args.host, args.port))

    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


def main() -> None:
    """Main CLI entry point for the ``apriori`` command."""
    parser = argparse.ArgumentParser(
        prog="apriori",
        description="A-Priori knowledge graph system",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # apriori ui
    ui_parser = subparsers.add_parser(
        "ui",
        help="Start the read-only Graph API and dashboard server",
    )
    ui_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind the server to (default: 127.0.0.1)",
    )
    ui_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the server to (default: 8000)",
    )
    ui_parser.add_argument(
        "--db",
        default=None,
        metavar="PATH",
        help="Path to SQLite database (default: from config or ./apriori.db)",
    )
    ui_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on code changes (development only)",
    )

    args = parser.parse_args()

    if args.command == "ui":
        _cmd_ui(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
