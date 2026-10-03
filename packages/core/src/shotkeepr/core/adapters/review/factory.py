"""Review is usable offline, without ExifTool or model weights at startup."""

from pathlib import Path

from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.repositories import SqlSessionRepository, SqlShotRepository
from shotkeepr.core.adapters.persistence.review import SqlReviewRepository
from shotkeepr.core.adapters.review.xmp import ExifToolXmpWriter
from shotkeepr.core.application.review import ReviewService


def review_service(db: Database, data: Path) -> ReviewService:
    return ReviewService(
        SqlShotRepository(db),
        SqlSessionRepository(db),
        SqlReviewRepository(db),
        ExifToolXmpWriter(data / "export-locks"),
    )
