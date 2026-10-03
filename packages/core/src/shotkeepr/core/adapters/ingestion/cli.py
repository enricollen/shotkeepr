"""Importazione e consultazione headless del catalogo fotografico."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.adapters.grouping.factory import grouping_service
from shotkeepr.core.adapters.ingestion.source import ExifToolPhotoSource
from shotkeepr.core.adapters.paths import app_data_dir
from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.migrate import upgrade_to_head
from shotkeepr.core.adapters.persistence.repositories import (
    SqlCatalogWriter,
    SqlSessionRepository,
    SqlShotRepository,
)
from shotkeepr.core.adapters.quality.factory import exposure_service, sharpness_service
from shotkeepr.core.adapters.review.factory import review_service
from shotkeepr.core.application.exposure import ExposureService
from shotkeepr.core.application.ingestion import ImportProgress, PhotoImportService
from shotkeepr.core.application.sharpness import SharpnessService
from shotkeepr.core.domain.catalog import ImageFile, Session, Shot
from shotkeepr.core.domain.catalog.grouping import DEFAULT_GAP_SECONDS, BurstGrouping, GroupingError
from shotkeepr.core.domain.catalog.ingestion import CatalogImportError
from shotkeepr.core.domain.catalog.review import ReviewError, ReviewStatus, ShotReview
from shotkeepr.core.domain.quality.exposure import ExposureError, ExposureMeasurement
from shotkeepr.core.domain.quality.sharpness import SharpnessError, SharpnessMeasurement


def configure_photos_cli(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="photo_command", required=True)
    ingest = commands.add_parser("import", help="Importa una cartella senza alterare gli originali")
    ingest.add_argument("source", type=Path)
    ingest.add_argument(
        "--no-subfolders", action="store_true", help="Non includere le sottocartelle"
    )
    show = commands.add_parser("show", help="Mostra scatti, metadati, anteprime ed esclusioni")
    show.add_argument("session_id", type=uuid.UUID)
    listing = commands.add_parser("list", help="Elenca le sessioni persistenti")
    exposure = commands.add_parser(
        "exposure", help="Misura l'esposizione delle anteprime di una sessione"
    )
    exposure.add_argument("session_id", type=uuid.UUID)
    review = commands.add_parser(
        "review", help="Salva una decisione manuale, senza scrivere sidecar"
    )
    review.add_argument("shot_id", type=uuid.UUID)
    review.add_argument("status", type=ReviewStatus, choices=list(ReviewStatus))
    export = commands.add_parser(
        "export-xmp", help="Pianifica o scrive i sidecar XMP della sessione"
    )
    export.add_argument("session_id", type=uuid.UUID)
    export.add_argument(
        "--write",
        action="store_true",
        help="Conferma la scrittura/merge dei sidecar accanto agli originali (default: solo piano)",
    )
    grouping = commands.add_parser("group", help="Raggruppa le raffiche temporali della sessione")
    grouping.add_argument("session_id", type=uuid.UUID)
    grouping.add_argument("--gap-seconds", type=float, default=DEFAULT_GAP_SECONDS)
    sharpness = commands.add_parser(
        "sharpness", help="Misura il dettaglio globale delle anteprime, non il fuoco del soggetto"
    )
    sharpness.add_argument("session_id", type=uuid.UUID)
    for command in (ingest, show, listing, exposure, review, export, grouping, sharpness):
        command.add_argument(
            "--data-dir", type=Path, default=None, help="Directory database e cache"
        )


def _session_json(session: Session) -> dict[str, object]:
    return {
        "session_id": str(session.session_id),
        "source_folder": str(session.source_folder),
        "include_subfolders": session.include_subfolders,
        "status": session.status.value,
        "processed": session.checkpoint,
        "started_at": session.started_at.isoformat(),
        "excluded": [
            {"path": str(file.path), "reason": file.reason.value, "detail": file.detail}
            for file in session.excluded
        ],
    }


def _file_json(file: ImageFile, preview: Path) -> dict[str, object]:
    metadata = {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in asdict(file.metadata).items()
    }
    return {
        "file_id": str(file.file_id),
        "path": str(file.path),
        "format": file.format,
        "kind": file.kind.value,
        "size_bytes": file.size,
        "sha256": file.fingerprint,
        "metadata": metadata,
        "preview_path": str(preview),
    }


def _shot_json(shot: Shot, cache: Path) -> dict[str, object]:
    from shotkeepr.core.adapters.ingestion.previews import PillowRawPreviewStore  # noqa: PLC0415

    previews = PillowRawPreviewStore(cache)
    return {
        "shot_id": str(shot.shot_id),
        "group_id": str(shot.group_id) if shot.group_id is not None else None,
        "content_hash": shot.content_hash,
        "capture_time": shot.capture_time.isoformat() if shot.capture_time is not None else None,
        "is_raw_pair": shot.is_raw_pair,
        "files": [_file_json(file, previews.path_for(file)) for file in shot.files],
    }


def _exposure_json(result: ExposureMeasurement) -> dict[str, object]:
    return {
        "shot_id": str(result.shot_id),
        "source_fingerprint": result.source_fingerprint,
        "preview_sha256": result.preview_sha256,
        "analyzer_version": result.analyzer_version,
        "measured_at": result.measured_at.isoformat(),
        **asdict(result.metrics),
        "score": result.metrics.score,
    }


def _sharpness_json(result: SharpnessMeasurement) -> dict[str, object]:
    return {
        "shot_id": str(result.shot_id),
        "source_fingerprint": result.source_fingerprint,
        "preview_sha256": result.preview_sha256,
        "analyzer_version": result.analyzer_version,
        "measured_at": result.measured_at.isoformat(),
        **asdict(result.metrics),
    }


def _measure_previews(
    session: Session, shots: Sequence[Shot], service: ExposureService | SharpnessService
) -> dict[str, object]:
    exposure = isinstance(service, ExposureService)
    label = "Esposizione" if exposure else "Nitidezza"
    measured: list[dict[str, object]] = []
    for index, shot in enumerate(shots, start=1):
        result = service.measure(shot.shot_id)
        measured.append(
            _exposure_json(result)
            if isinstance(result, ExposureMeasurement)
            else _sharpness_json(result)
        )
        print(f"{label} anteprima: {index}/{len(shots)} scatti", file=sys.stderr)
    return {
        "session_id": str(session.session_id),
        "status": session.status.value,
        "full_analysis_performed": False,
        "exposure" if exposure else "sharpness": measured,
    }


def _review_json(review: ShotReview) -> dict[str, object]:
    return {
        "shot_id": str(review.shot_id),
        "status": review.status.value,
        "updated_at": review.updated_at.isoformat() if review.updated_at is not None else None,
    }


def _progress(progress: ImportProgress) -> None:
    print(
        f"{progress.processed} file: {progress.imported} importati, "
        f"{progress.excluded} esclusi - {progress.path.name}",
        file=sys.stderr,
    )


def _grouping_json(result: BurstGrouping) -> dict[str, object]:
    return {
        "session_id": str(result.session_id),
        "gap_seconds": result.gap_seconds,
        "method_version": result.method_version,
        "grouped_at": result.grouped_at.isoformat() if result.grouped_at is not None else None,
        "ungrouped_shots": result.ungrouped_shots,
        "groups": [
            {
                **asdict(group),
                "group_id": str(group.group_id),
                "first_capture": group.first_capture.isoformat(),
                "last_capture": group.last_capture.isoformat(),
            }
            for group in result.groups
        ],
    }


def _xmp_progress(index: int, total: int, paths: Sequence[Path]) -> None:
    delivered = ", ".join(str(path) for path in paths)
    print(f"XMP: {index}/{total} scatti - {delivered}", file=sys.stderr)


def _import(args: argparse.Namespace, data: Path) -> dict[str, object]:
    from shotkeepr.core.adapters.ingestion.previews import PillowRawPreviewStore  # noqa: PLC0415

    source = ExifToolPhotoSource()
    folder = source.validate_folder(args.source)
    if data.is_relative_to(folder):
        raise CatalogImportError("database e cache devono essere esterni alla cartella sorgente")
    database = Database.at(data / "shotkeepr.db")
    try:
        upgrade_to_head(database.url)
        service = PhotoImportService(
            source,
            PillowRawPreviewStore(data / "previews"),
            SqlSessionRepository(database),
            SqlCatalogWriter(database),
        )
        result = service.import_folder(folder, recursive=not args.no_subfolders, progress=_progress)
        return {
            **_session_json(result.session),
            "shots": len(result.shots),
            "files": sum(len(shot.files) for shot in result.shots),
            "raw_pairs": sum(shot.is_raw_pair for shot in result.shots),
            "analysis_performed": False,
        }
    finally:
        database.dispose()


def _read(args: argparse.Namespace, data: Path) -> dict[str, object]:
    if not (data / "shotkeepr.db").is_file():
        raise CatalogImportError("catalogo non presente: importare prima una cartella")
    database = Database.at(data / "shotkeepr.db")
    try:
        upgrade_to_head(database.url)
        sessions = SqlSessionRepository(database)
        if args.photo_command == "list":
            return {"sessions": [_session_json(session) for session in sessions.list()]}
        review = review_service(database, data)
        if args.photo_command == "review":
            return _review_json(review.set_status(args.shot_id, args.status))
        session = sessions.get(args.session_id)
        if session is None:
            raise CatalogImportError("sessione non presente nel catalogo")
        if args.photo_command == "group":
            return _grouping_json(
                grouping_service(database).regroup(session.session_id, args.gap_seconds)
            )
        shots = SqlShotRepository(database).list_by_session(session.session_id)
        exposure = exposure_service(database, data)
        if args.photo_command in {"exposure", "sharpness"}:
            service = (
                exposure if args.photo_command == "exposure" else sharpness_service(database, data)
            )
            return _measure_previews(session, shots, service)
        if args.photo_command == "export-xmp":
            exports = review.export_session(
                session.session_id, write=args.write, progress=_xmp_progress
            )
            plan = [
                {
                    "shot_id": str(item.shot_id),
                    "status": item.status.value,
                    "paths": [str(path) for path in item.paths],
                }
                for item in exports
            ]
            return {"session_id": str(session.session_id), "written": args.write, "sidecars": plan}
        reviews = review.reviews.get_many([shot.shot_id for shot in shots])
        measurements = exposure.results.get_many([shot.shot_id for shot in shots])
        sharpness = sharpness_service(database, data).results.get_many(
            [shot.shot_id for shot in shots]
        )
        return {
            **_session_json(session),
            "grouping": _grouping_json(grouping_service(database).get(session.session_id)),
            "shots": [
                {
                    **_shot_json(shot, data / "previews"),
                    "review": _review_json(reviews.get(shot.shot_id, ShotReview(shot.shot_id))),
                    "sharpness": (
                        _sharpness_json(sharpness[shot.shot_id])
                        if shot.shot_id in sharpness
                        else None
                    ),
                    "exposure": (
                        _exposure_json(measurements[shot.shot_id])
                        if shot.shot_id in measurements
                        else None
                    ),
                }
                for shot in shots
            ],
        }
    finally:
        database.dispose()


def run_photos(args: argparse.Namespace) -> int:
    try:
        data = (args.data_dir if args.data_dir is not None else app_data_dir()).resolve()
        result = _import(args, data) if args.photo_command == "import" else _read(args, data)
        print(json.dumps(result, indent=2))
    except (
        CatalogImportError,
        ExposureError,
        SharpnessError,
        ReviewError,
        GroupingError,
        OSError,
        SQLAlchemyError,
    ) as exc:
        print(f"Catalogo non disponibile: {exc}", file=sys.stderr)
        return 1
    return 0
