"""Partial preview detail measurements; no full-analysis state changes."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.models import SharpnessMeasurementRow
from shotkeepr.core.domain.quality.sharpness import SharpnessMeasurement, SharpnessMetrics


def _from_row(row: SharpnessMeasurementRow) -> SharpnessMeasurement:
    return SharpnessMeasurement(
        row.shot_id,
        row.source_fingerprint,
        row.preview_sha256,
        row.analyzer_version,
        row.measured_at,
        SharpnessMetrics(row.width, row.height, row.laplacian_variance, row.gradient_energy),
    )


class SqlSharpnessRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, shot_id: uuid.UUID) -> SharpnessMeasurement | None:
        with self._db.transaction() as tx:
            row = tx.get(SharpnessMeasurementRow, shot_id)
            return None if row is None else _from_row(row)

    def get_many(self, shot_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, SharpnessMeasurement]:
        if not shot_ids:
            return {}
        with self._db.transaction() as tx:
            rows = tx.scalars(
                select(SharpnessMeasurementRow).where(SharpnessMeasurementRow.shot_id.in_(shot_ids))
            )
            return {row.shot_id: _from_row(row) for row in rows}

    def save(self, result: SharpnessMeasurement) -> None:
        stmt = insert(SharpnessMeasurementRow).values(
            shot_id=result.shot_id,
            source_fingerprint=result.source_fingerprint,
            preview_sha256=result.preview_sha256,
            analyzer_version=result.analyzer_version,
            measured_at=result.measured_at,
            **asdict(result.metrics),
        )
        with self._db.transaction() as tx:
            tx.execute(
                stmt.on_conflict_do_update(
                    index_elements=[SharpnessMeasurementRow.shot_id],
                    set_={
                        col.name: stmt.excluded[col.name]
                        for col in stmt.table.c
                        if col.name != "shot_id"
                    },
                )
            )
