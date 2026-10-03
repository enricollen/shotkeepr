"""Manual review is independent of photographic analysis and never deletes files."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class ReviewStatus(StrEnum):
    KEEP = "KEEP"
    REJECT = "REJECT"
    REVIEW = "REVIEW"


@dataclass(frozen=True, slots=True)
class ShotReview:
    shot_id: uuid.UUID
    status: ReviewStatus = ReviewStatus.REVIEW
    updated_at: datetime | None = None

    @property
    def rating(self) -> int:
        return {ReviewStatus.KEEP: 5, ReviewStatus.REJECT: -1, ReviewStatus.REVIEW: 0}[self.status]

    @property
    def label(self) -> str:
        return {
            ReviewStatus.KEEP: "Green",
            ReviewStatus.REJECT: "Red",
            ReviewStatus.REVIEW: "Yellow",
        }[self.status]


@dataclass(frozen=True, slots=True)
class XmpExportItem:
    shot_id: uuid.UUID
    status: ReviewStatus
    paths: tuple[Path, ...]


class ReviewError(RuntimeError):
    """Review/export cannot be completed safely."""


class ReviewShotNotFoundError(ReviewError):
    """The requested shot is absent from the catalog."""


class XmpUnavailableError(ReviewError):
    """ExifTool is unavailable; manual review remains usable."""
