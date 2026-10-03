"""Risultati parziali di esposizione, senza promuovere la sessione ad ANALYZED."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.models import ExposureMeasurementRow
from shotkeepr.core.domain.quality.exposure import ExposureMeasurement, ExposureMetrics


def _from_row(row: ExposureMeasurementRow) -> ExposureMeasurement:
    return ExposureMeasurement(
        shot_id=row.shot_id,
        source_fingerprint=row.source_fingerprint,
        preview_sha256=row.preview_sha256,
        analyzer_version=row.analyzer_version,
        measured_at=row.measured_at,
        metrics=ExposureMetrics(
            width=row.width,
            height=row.height,
            mean_luma=row.mean_luma,
            highlights_fraction=row.highlights_fraction,
            shadows_fraction=row.shadows_fraction,
        ),
    )


class SqlExposureRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, shot_id: uuid.UUID) -> ExposureMeasurement | None:
        with self._db.transaction() as tx:
            row = tx.get(ExposureMeasurementRow, shot_id)
            return None if row is None else _from_row(row)

    def get_many(self, shot_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, ExposureMeasurement]:
        if not shot_ids:
            return {}
        with self._db.transaction() as tx:
            stmt = select(ExposureMeasurementRow).where(
                ExposureMeasurementRow.shot_id.in_(shot_ids)
            )
            return {row.shot_id: _from_row(row) for row in tx.scalars(stmt)}

    def save(self, measurement: ExposureMeasurement) -> None:
        metrics = measurement.metrics
        stmt = insert(ExposureMeasurementRow).values(
            shot_id=measurement.shot_id,
            source_fingerprint=measurement.source_fingerprint,
            preview_sha256=measurement.preview_sha256,
            analyzer_version=measurement.analyzer_version,
            measured_at=measurement.measured_at,
            width=metrics.width,
            height=metrics.height,
            mean_luma=metrics.mean_luma,
            highlights_fraction=metrics.highlights_fraction,
            shadows_fraction=metrics.shadows_fraction,
        )
        with self._db.transaction() as tx:
            tx.execute(
                stmt.on_conflict_do_update(
                    index_elements=[ExposureMeasurementRow.shot_id],
                    set_={
                        col.name: stmt.excluded[col.name]
                        for col in stmt.table.c
                        if col.name != "shot_id"
                    },
                )
            )
