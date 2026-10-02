"""Punto di ingresso del nucleo (`shotkeepr-core`)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from shotkeepr.core import __version__
from shotkeepr.core.adapters.observability.logging import configure_logging
from shotkeepr.core.adapters.paths import app_data_dir, db_path, log_dir, runtime_dir
from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.migrate import upgrade_to_head
from shotkeepr.core.adapters.persistence.settings import SqlSettingsRepository
from shotkeepr.core.adapters.secrets.stores import default_secret_store
from shotkeepr.core.api.server import serve as run_server
from shotkeepr.core.application.configuration import ConfigurationService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shotkeepr-core", description="Nucleo di ShotKeepr")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Avvia l'API locale su 127.0.0.1")
    serve.add_argument("--port", type=int, default=None, help="Porta fissa (default: libera)")
    return parser


def _run_serve(port: int | None) -> int:
    data_dir = app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(log_dir())
    db = Database.at(db_path())
    upgrade_to_head(db.url)
    service = ConfigurationService(SqlSettingsRepository(db), default_secret_store())
    run_server(service, runtime_dir(), port=port)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return _run_serve(args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
