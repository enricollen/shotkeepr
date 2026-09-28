"""Entità del catalogo (ent-001…ent-005)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


def _now() -> datetime:
    return datetime.now(UTC)


class SessionStatus(StrEnum):
    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    PAUSED = "PAUSED"
    ANALYZED = "ANALYZED"
    FAILED = "FAILED"


class FileKind(StrEnum):
    RAW = "RAW"
    STANDARD = "STANDARD"


class ExclusionReason(StrEnum):
    UNSUPPORTED = "UNSUPPORTED"
    CORRUPTED = "CORRUPTED"
    UNREADABLE = "UNREADABLE"


@dataclass(frozen=True, slots=True)
class ShotMetadata:
    """ent-004 — metadati EXIF di un file."""

    camera_model: str | None = None
    camera_serial: str | None = None
    lens: str | None = None
    focal_mm: float | None = None
    exposure_s: float | None = None
    aperture: float | None = None
    iso: int | None = None
    capture_time: datetime | None = None


@dataclass(slots=True)
class ImageFile:
    """ent-003 — file fisico appartenente a uno scatto."""

    path: Path
    format: str
    kind: FileKind
    size: int
    fingerprint: str
    metadata: ShotMetadata = field(default_factory=ShotMetadata)
    file_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(slots=True)
class Shot:
    """ent-002 — unità di selezione, eventualmente coppia RAW+JPEG."""

    session_id: uuid.UUID
    content_hash: str
    files: list[ImageFile] = field(default_factory=list)
    capture_time: datetime | None = None
    group_id: uuid.UUID | None = None
    shot_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @property
    def is_raw_pair(self) -> bool:
        kinds = {f.kind for f in self.files}
        return kinds == {FileKind.RAW, FileKind.STANDARD}


@dataclass(frozen=True, slots=True)
class ExcludedFile:
    """ent-005 — file non supportato o corrotto."""

    path: Path
    reason: ExclusionReason
    detail: str = ""


@dataclass(slots=True)
class Session:
    """ent-001 — lavoro di selezione su una cartella sorgente."""

    source_folder: Path
    include_subfolders: bool = True
    profile_id: uuid.UUID | None = None
    status: SessionStatus = SessionStatus.CREATED
    checkpoint: int = 0
    started_at: datetime = field(default_factory=_now)
    excluded: list[ExcludedFile] = field(default_factory=list)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
