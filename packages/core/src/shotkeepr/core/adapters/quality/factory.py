"""Composizione del servizio usato da CLI e API native/container."""

from pathlib import Path

from shotkeepr.core.adapters.ingestion.previews import PillowRawPreviewStore
from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.exposure import SqlExposureRepository
from shotkeepr.core.adapters.persistence.repositories import SqlShotRepository
from shotkeepr.core.adapters.persistence.sharpness import SqlSharpnessRepository
from shotkeepr.core.adapters.quality.exposure import PillowExposureAnalyzer
from shotkeepr.core.adapters.quality.sharpness import PillowSharpnessAnalyzer
from shotkeepr.core.application.exposure import ExposureService
from shotkeepr.core.application.sharpness import SharpnessService


def exposure_service(database: Database, data: Path) -> ExposureService:
    return ExposureService(
        SqlShotRepository(database),
        PillowRawPreviewStore(data / "previews"),
        SqlExposureRepository(database),
        PillowExposureAnalyzer(),
    )


def sharpness_service(database: Database, data: Path) -> SharpnessService:
    return SharpnessService(
        SqlShotRepository(database),
        PillowRawPreviewStore(data / "previews"),
        SqlSharpnessRepository(database),
        PillowSharpnessAnalyzer(),
    )
