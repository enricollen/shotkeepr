"""Punto di ingresso del nucleo (`shotkeepr-core`)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from http.client import HTTPException
from pathlib import Path

from shotkeepr.core import __version__
from shotkeepr.core.adapters.grouping.factory import grouping_service
from shotkeepr.core.adapters.ingestion.cli import configure_photos_cli, run_photos
from shotkeepr.core.adapters.models.cli import configure_models_cli, run_models
from shotkeepr.core.adapters.observability.logging import configure_logging
from shotkeepr.core.adapters.paths import app_data_dir, db_path, log_dir, runtime_dir
from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.migrate import upgrade_to_head
from shotkeepr.core.adapters.persistence.repositories import (
    SqlCatalogWriter,
    SqlSessionRepository,
    SqlShotRepository,
)
from shotkeepr.core.adapters.persistence.settings import SqlSettingsRepository
from shotkeepr.core.adapters.quality.factory import exposure_service, sharpness_service
from shotkeepr.core.adapters.review.factory import review_service
from shotkeepr.core.adapters.secrets.stores import default_secret_store
from shotkeepr.core.api.healthcheck import HealthCheckError, check_health
from shotkeepr.core.api.import_jobs import ImportJobs
from shotkeepr.core.api.server import BIND_HOSTS, LOCALHOST
from shotkeepr.core.api.server import serve as run_server
from shotkeepr.core.application.configuration import ConfigurationService
from shotkeepr.core.application.ingestion import PhotoImportService


def _port(value: str) -> int:
    port = int(value)
    if not 0 < port < 65536:
        raise argparse.ArgumentTypeError("la porta deve essere compresa tra 1 e 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shotkeepr-core", description="Nucleo di ShotKeepr")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Avvia l'API locale")
    serve.add_argument("--port", type=_port, default=None, help="Porta fissa (default: libera)")
    serve.add_argument(
        "--host",
        choices=BIND_HOSTS,
        default=LOCALHOST,
        help="Bind dell'API (default: loopback; 0.0.0.0 solo per container)",
    )
    serve.add_argument("--runtime-dir", type=Path, default=None, help="Directory token e porta")
    serve.add_argument("--data-dir", type=Path, default=None, help="Directory database e log")

    health = subparsers.add_parser("healthcheck", help="Verifica la salute del nucleo locale")
    health.add_argument("--port", type=_port, default=None, help="Porta del nucleo")
    health.add_argument(
        "--runtime-dir", type=Path, default=None, help="Directory del file api.port"
    )
    models = subparsers.add_parser("models", help="Gestione dei modelli AI versionati")
    configure_models_cli(models)
    photos = subparsers.add_parser("photos", help="Importazione e catalogo fotografico")
    configure_photos_cli(photos)
    return parser


def _import_jobs(db: Database, data: Path) -> ImportJobs:
    from shotkeepr.core.adapters.ingestion.previews import PillowRawPreviewStore  # noqa: PLC0415
    from shotkeepr.core.adapters.ingestion.source import ExifToolPhotoSource  # noqa: PLC0415

    sessions = SqlSessionRepository(db)
    shots = SqlShotRepository(db)
    previews = PillowRawPreviewStore(data / "previews")
    writer = SqlCatalogWriter(db)

    def factory() -> PhotoImportService:
        return PhotoImportService(ExifToolPhotoSource(), previews, sessions, writer)

    return ImportJobs(factory, sessions, shots, previews)


def _run_serve(
    port: int | None,
    runtime: Path | None = None,
    data: Path | None = None,
    *,
    host: str = LOCALHOST,
) -> int:
    data_dir = data if data is not None else app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(data_dir / "logs" if data is not None else log_dir())
    db = Database.at(data_dir / "shotkeepr.db" if data is not None else db_path())
    imports = _import_jobs(db, data_dir)
    try:
        upgrade_to_head(db.url)
        service = ConfigurationService(SqlSettingsRepository(db), default_secret_store())
        default_runtime = data_dir / "run" if data is not None else runtime_dir()
        run_server(
            service,
            runtime if runtime is not None else default_runtime,
            port=port,
            host=host,
            import_jobs=imports,
            exposure_service=exposure_service(db, data_dir),
            review_service=review_service(db, data_dir),
            grouping_service=grouping_service(db),
            sharpness_service=sharpness_service(db, data_dir),
        )
    finally:
        imports.shutdown()
        db.dispose()
    return 0


def _run_healthcheck(port: int | None, runtime: Path | None) -> int:
    try:
        if port is None:
            directory = runtime if runtime is not None else runtime_dir()
            port = int((directory / "api.port").read_text(encoding="utf-8"))
        check_health(port)
    except (OSError, HTTPException, ValueError, UnicodeError, HealthCheckError) as exc:
        print(f"Nucleo non disponibile: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return _run_serve(args.port, args.runtime_dir, args.data_dir, host=args.host)
    if args.command == "healthcheck":
        return _run_healthcheck(args.port, args.runtime_dir)
    if args.command == "models":
        return run_models(args)
    if args.command == "photos":
        return run_photos(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
