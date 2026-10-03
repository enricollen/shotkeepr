"""Contratti di importazione e catalogo esposti alla GUI."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shotkeepr.core.domain.catalog import (
    ExclusionReason,
    FileKind,
    ImageFile,
    Session,
    SessionStatus,
    Shot,
)
from shotkeepr.core.domain.catalog.grouping import (
    DEFAULT_GAP_SECONDS,
    MAX_GAP_SECONDS,
    MIN_GAP_SECONDS,
    BurstGroup,
    BurstGrouping,
)
from shotkeepr.core.domain.catalog.review import ReviewStatus, ShotReview
from shotkeepr.core.domain.quality.exposure import ExposureMeasurement
from shotkeepr.core.domain.quality.sharpness import SharpnessMeasurement


class ApiError(BaseModel):
    detail: str


class ImportRequest(BaseModel):
    source_folder: str = Field(min_length=1, max_length=4096)
    include_subfolders: bool = True


class ImportJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ImportJobOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "required": [
                "job_id",
                "session_id",
                "source_folder",
                "status",
                "processed",
                "imported_files",
                "excluded_files",
                "shots",
                "current_file",
                "error",
                "cancel_requested",
            ],
        }
    )

    job_id: uuid.UUID
    session_id: uuid.UUID
    source_folder: str
    status: ImportJobStatus = ImportJobStatus.QUEUED
    processed: int = 0
    imported_files: int = 0
    excluded_files: int = 0
    shots: int = 0
    current_file: str | None = None
    error: str | None = None
    cancel_requested: bool = False


class ExcludedFileOut(BaseModel):
    path: str
    reason: ExclusionReason
    detail: str


class BurstRequest(BaseModel):
    gap_seconds: float = Field(
        default=DEFAULT_GAP_SECONDS,
        ge=MIN_GAP_SECONDS,
        le=MAX_GAP_SECONDS,
        allow_inf_nan=False,
        strict=True,
    )


class BurstGroupOut(BaseModel):
    group_id: uuid.UUID
    camera_model: str
    camera_serial: str
    shots: int
    first_capture: datetime
    last_capture: datetime

    @classmethod
    def from_domain(cls, group: BurstGroup) -> BurstGroupOut:
        return cls(**asdict(group))


class BurstGroupingOut(BaseModel):
    session_id: uuid.UUID
    gap_seconds: float | None
    method_version: str | None
    grouped_at: datetime | None
    groups: list[BurstGroupOut]
    ungrouped_shots: int

    @classmethod
    def from_domain(cls, result: BurstGrouping) -> BurstGroupingOut:
        return cls(**asdict(result))


class SessionOut(BaseModel):
    session_id: uuid.UUID
    source_folder: str
    include_subfolders: bool
    status: SessionStatus
    processed: int
    shots: int
    started_at: datetime
    excluded: list[ExcludedFileOut]
    grouping: BurstGroupingOut | None = None

    @classmethod
    def from_domain(
        cls, session: Session, count: int, grouping: BurstGrouping | None = None
    ) -> SessionOut:
        return cls(
            grouping=None if grouping is None else BurstGroupingOut.from_domain(grouping),
            session_id=session.session_id,
            source_folder=str(session.source_folder),
            include_subfolders=session.include_subfolders,
            status=session.status,
            processed=session.checkpoint,
            shots=count,
            started_at=session.started_at,
            excluded=[
                ExcludedFileOut(path=str(item.path), reason=item.reason, detail=item.detail)
                for item in session.excluded
            ],
        )


class MetadataOut(BaseModel):
    camera_model: str | None
    camera_serial: str | None
    lens: str | None
    focal_mm: float | None
    exposure_s: float | None
    aperture: float | None
    iso: int | None
    capture_time: datetime | None


class PhotoFileOut(BaseModel):
    file_id: uuid.UUID
    path: str
    format: str
    kind: FileKind
    size_bytes: int
    metadata: MetadataOut

    @classmethod
    def from_domain(cls, file: ImageFile) -> PhotoFileOut:
        return cls(
            file_id=file.file_id,
            path=str(file.path),
            format=file.format,
            kind=file.kind,
            size_bytes=file.size,
            metadata=MetadataOut(**asdict(file.metadata)),
        )


class ExposureOut(BaseModel):
    shot_id: uuid.UUID
    source_fingerprint: str
    preview_sha256: str
    analyzer_version: str
    measured_at: datetime
    width: int
    height: int
    mean_luma: float = Field(ge=0, le=1)
    highlights_fraction: float = Field(ge=0, le=1)
    shadows_fraction: float = Field(ge=0, le=1)
    score: float = Field(ge=0, le=100)

    @classmethod
    def from_domain(cls, result: ExposureMeasurement) -> ExposureOut:
        return cls(
            shot_id=result.shot_id,
            source_fingerprint=result.source_fingerprint,
            preview_sha256=result.preview_sha256,
            analyzer_version=result.analyzer_version,
            measured_at=result.measured_at,
            **asdict(result.metrics),
            score=result.metrics.score,
        )


class SharpnessOut(BaseModel):
    shot_id: uuid.UUID
    source_fingerprint: str
    preview_sha256: str
    analyzer_version: str
    measured_at: datetime
    width: int = Field(ge=3, le=512)
    height: int = Field(ge=3, le=512)
    laplacian_variance: float = Field(ge=0, le=16, allow_inf_nan=False)
    gradient_energy: float = Field(ge=0, le=1, allow_inf_nan=False)

    @classmethod
    def from_domain(cls, result: SharpnessMeasurement) -> SharpnessOut:
        return cls(
            shot_id=result.shot_id,
            source_fingerprint=result.source_fingerprint,
            preview_sha256=result.preview_sha256,
            analyzer_version=result.analyzer_version,
            measured_at=result.measured_at,
            **asdict(result.metrics),
        )


class ReviewOut(BaseModel):
    shot_id: uuid.UUID
    status: ReviewStatus
    updated_at: datetime | None

    @classmethod
    def from_domain(cls, review: ShotReview) -> ReviewOut:
        return cls(**asdict(review))


class ReviewRequest(BaseModel):
    status: ReviewStatus


class XmpRequest(BaseModel):
    confirm: Literal[True]
    expected_status: ReviewStatus


class XmpOut(BaseModel):
    shot_id: uuid.UUID
    status: ReviewStatus
    paths: list[str]


class ShotOut(BaseModel):
    shot_id: uuid.UUID
    capture_time: datetime | None
    is_raw_pair: bool
    files: list[PhotoFileOut]
    exposure: ExposureOut | None = None
    review: ReviewOut | None = None
    group_id: uuid.UUID | None = None
    sharpness: SharpnessOut | None = None

    @classmethod
    def from_domain(
        cls,
        shot: Shot,
        exposure: ExposureMeasurement | None = None,
        review: ShotReview | None = None,
        sharpness: SharpnessMeasurement | None = None,
    ) -> ShotOut:
        return cls(
            shot_id=shot.shot_id,
            capture_time=shot.capture_time,
            group_id=shot.group_id,
            is_raw_pair=shot.is_raw_pair,
            files=[PhotoFileOut.from_domain(file) for file in shot.files],
            exposure=None if exposure is None else ExposureOut.from_domain(exposure),
            review=ReviewOut.from_domain(review or ShotReview(shot.shot_id)),
            sharpness=None if sharpness is None else SharpnessOut.from_domain(sharpness),
        )


class ShotPageOut(BaseModel):
    items: list[ShotOut]
    total: int
    offset: int
    limit: int
