"""Explicit grouping of a persisted session; no photo decoding or model inference."""

import uuid

from shotkeepr.core.application.ports import GroupingRepository
from shotkeepr.core.domain.catalog.grouping import BurstGrouping, validate_gap


class GroupingService:
    def __init__(self, repository: GroupingRepository) -> None:
        self.repository = repository

    def get(self, session_id: uuid.UUID) -> BurstGrouping:
        return self.repository.get(session_id)

    def regroup(self, session_id: uuid.UUID, gap_seconds: float) -> BurstGrouping:
        validate_gap(gap_seconds)
        return self.repository.regroup(session_id, gap_seconds)
