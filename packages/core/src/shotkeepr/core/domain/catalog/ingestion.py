"""Regole pure di catalogazione e abbinamento RAW+JPEG (FR-005)."""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from shotkeepr.core.domain.catalog.model import ExclusionReason, FileKind, ImageFile, Shot


class CatalogImportError(RuntimeError):
    """Errore di ingestione o servizio necessario non disponibile."""


class ImportCancelledError(CatalogImportError):
    """Importazione annullata esplicitamente prima della pubblicazione degli scatti."""


class ExifToolUnavailableError(CatalogImportError):
    """Il servizio di metadati richiesto non e' installato."""


class FileInspectionError(CatalogImportError):
    def __init__(self, reason: ExclusionReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


def _compatible_cameras(raw: ImageFile, jpeg: ImageFile) -> bool:
    return all(
        first is None or second is None or first == second
        for first, second in (
            (raw.metadata.camera_model, jpeg.metadata.camera_model),
            (raw.metadata.camera_serial, jpeg.metadata.camera_serial),
        )
    )


def _shot(session_id: uuid.UUID, files: Sequence[ImageFile]) -> Shot:
    fingerprints = sorted({file.fingerprint for file in files})
    content_hash = hashlib.sha256("\n".join(fingerprints).encode("ascii")).hexdigest()
    return Shot(
        session_id=session_id,
        content_hash=content_hash,
        files=list(files),
        capture_time=files[0].metadata.capture_time,
    )


def build_shots(session_id: uuid.UUID, files: Sequence[ImageFile]) -> list[Shot]:
    """Abbina solo coppie univoche; gli alias con contenuto identico restano referenziati."""
    groups: dict[tuple[Path, str, datetime | None], list[ImageFile]] = defaultdict(list)
    for file in files:
        groups[(file.path.parent, file.path.stem, file.metadata.capture_time)].append(file)
    units: list[list[ImageFile]] = []
    for (_, _, captured), candidates in groups.items():
        raws = [file for file in candidates if file.kind is FileKind.RAW]
        jpegs = [file for file in candidates if file.format == "JPEG"]
        if (
            captured is not None
            and len(raws) == 1
            and len(jpegs) == 1
            and _compatible_cameras(raws[0], jpegs[0])
        ):
            units.append([raws[0], jpegs[0]])
            paired = {raws[0].file_id, jpegs[0].file_id}
            units.extend([file] for file in candidates if file.file_id not in paired)
        else:
            units.extend([file] for file in candidates)
    shots: dict[str, Shot] = {}
    for unit in units:
        shot = _shot(session_id, unit)
        existing = shots.get(shot.content_hash)
        if existing is None:
            shots[shot.content_hash] = shot
        else:
            existing.files.extend(shot.files)
    return list(shots.values())
