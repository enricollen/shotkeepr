"""Current review and change history are published in the same SQLite transaction."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, text

from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.models import ManualStatusChangeRow, ShotReviewRow
from shotkeepr.core.domain.catalog import Shot
from shotkeepr.core.domain.catalog.review import ReviewStatus, ShotReview


def _from_row(row: ShotReviewRow) -> ShotReview:
    return ShotReview(row.shot_id, ReviewStatus(row.status), row.updated_at)


class SqlReviewRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, shot_id: uuid.UUID) -> ShotReview | None:
        with self._db.transaction() as tx:
            row = tx.get(ShotReviewRow, shot_id)
            return None if row is None else _from_row(row)

    def get_many(self, shot_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, ShotReview]:
        if not shot_ids:
            return {}
        with self._db.transaction() as tx:
            stmt = select(ShotReviewRow).where(ShotReviewRow.shot_id.in_(shot_ids))
            return {row.shot_id: _from_row(row) for row in tx.scalars(stmt)}

    def set_status(self, shot: Shot, status: ReviewStatus) -> ShotReview:
        with self._db.transaction() as tx:
            # Serialize read/change/audit, including requests from other core processes.
            tx.execute(text("BEGIN IMMEDIATE"))
            row = tx.get(ShotReviewRow, shot.shot_id)
            if row is not None and row.status == status.value:
                return _from_row(row)
            old = ReviewStatus.REVIEW.value if row is None else row.status
            now = datetime.now(UTC)
            if row is None:
                row = ShotReviewRow(shot_id=shot.shot_id, status=status.value, updated_at=now)
                tx.add(row)
            else:
                row.status, row.updated_at = status.value, now
            if old != status.value:
                tx.add(
                    ManualStatusChangeRow(
                        id=uuid.uuid4(),
                        session_id=shot.session_id,
                        shot_id=shot.shot_id,
                        old_status=old,
                        new_status=status.value,
                        at=now,
                    )
                )
            return _from_row(row)
