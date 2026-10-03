"""Publish all burst memberships and parameters in one serialized SQLite transaction."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import selectinload

from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.models import (
    BurstGroupingRow,
    GroupCorrectionRow,
    GroupRow,
    SelectionRunRow,
    SessionRow,
    ShotRow,
)
from shotkeepr.core.adapters.persistence.repositories import _shot_to_domain
from shotkeepr.core.domain.catalog import SessionStatus
from shotkeepr.core.domain.catalog.grouping import (
    BURST_METHOD,
    BurstGroup,
    BurstGrouping,
    GroupingError,
    GroupingSessionNotFoundError,
    build_bursts,
    grouping_fingerprint,
)


def _session(tx: OrmSession, session_id: uuid.UUID) -> SessionRow:
    row = tx.get(SessionRow, session_id)
    if row is None:
        raise GroupingSessionNotFoundError("Sessione non presente nel catalogo")
    return row


def _read(tx: OrmSession, session_id: uuid.UUID) -> BurstGrouping:
    _session(tx, session_id)
    config = tx.get(BurstGroupingRow, session_id)
    query = (
        select(
            GroupRow,
            func.count(ShotRow.id),
            func.min(ShotRow.capture_time),
            func.max(ShotRow.capture_time),
        )
        .join(ShotRow, ShotRow.group_id == GroupRow.id)
        .where(
            GroupRow.session_id == session_id,
            GroupRow.kind == "BURST",
            GroupRow.is_manual.is_(False),
        )
        .group_by(GroupRow.id)
        .order_by(func.min(ShotRow.capture_time), GroupRow.id)
    )
    groups: list[BurstGroup] = []
    for row, count, first, last in tx.execute(query):
        if row.camera_model is None or row.camera_serial is None or first is None or last is None:
            raise GroupingError("Metadati del raggruppamento persistente non validi")
        groups.append(BurstGroup(row.id, row.camera_model, row.camera_serial, count, first, last))
    ungrouped = tx.scalar(
        select(func.count())
        .select_from(ShotRow)
        .where(ShotRow.session_id == session_id, ShotRow.group_id.is_(None))
    )
    return BurstGrouping(
        session_id,
        None if config is None else config.gap_seconds,
        None if config is None else config.method_version,
        None if config is None else config.grouped_at,
        tuple(groups),
        int(ungrouped or 0),
    )


class SqlGroupingRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, session_id: uuid.UUID) -> BurstGrouping:
        with self._db.transaction() as tx:
            tx.execute(text("BEGIN"))
            return _read(tx, session_id)

    def regroup(self, session_id: uuid.UUID, gap_seconds: float) -> BurstGrouping:
        with self._db.transaction() as tx:
            tx.execute(text("BEGIN IMMEDIATE"))
            session = _session(tx, session_id)
            if SessionStatus(session.status) not in {
                SessionStatus.IMPORTED,
                SessionStatus.ANALYZED,
            }:
                raise GroupingError(
                    "Raggruppamento consentito solo su una sessione importata o analizzata"
                )
            existing = tx.scalars(select(GroupRow).where(GroupRow.session_id == session_id)).all()
            corrections = tx.scalar(
                select(GroupCorrectionRow.id)
                .where(GroupCorrectionRow.session_id == session_id)
                .limit(1)
            )
            runs = tx.scalar(
                select(SelectionRunRow.id).where(SelectionRunRow.session_id == session_id).limit(1)
            )
            if (
                corrections is not None
                or runs is not None
                or any(row.is_manual or row.kind != "BURST" for row in existing)
            ):
                raise GroupingError(
                    "Raggruppamento protetto: presenti correzioni, altri gruppi o selezioni"
                )
            rows = tx.scalars(
                select(ShotRow)
                .where(ShotRow.session_id == session_id)
                .options(selectinload(ShotRow.files))
            ).all()
            shots = [_shot_to_domain(row) for row in rows]
            planned = build_bursts(session_id, shots, gap_seconds)
            fingerprint = grouping_fingerprint(shots)
            config = tx.get(BurstGroupingRow, session_id)
            expected = {item.group.group_id: item.group for item in planned}
            assigned = {
                shot_id: item.group.group_id for item in planned for shot_id in item.shot_ids
            }
            if (
                config is not None
                and config.gap_seconds == gap_seconds
                and config.method_version == BURST_METHOD
                and config.input_sha256 == fingerprint
                and {row.id for row in existing} == set(expected)
                and all(
                    row.camera_model == expected[row.id].camera_model
                    and row.camera_serial == expected[row.id].camera_serial
                    for row in existing
                )
                and all(row.group_id == assigned.get(row.id) for row in rows)
            ):
                return _read(tx, session_id)
            tx.execute(
                update(ShotRow).where(ShotRow.session_id == session_id).values(group_id=None)
            )
            tx.execute(delete(GroupRow).where(GroupRow.session_id == session_id))
            tx.add_all(
                GroupRow(
                    id=item.group.group_id,
                    session_id=session_id,
                    kind="BURST",
                    is_manual=False,
                    camera_model=item.group.camera_model,
                    camera_serial=item.group.camera_serial,
                )
                for item in planned
            )
            tx.flush()
            for row in rows:
                row.group_id = assigned.get(row.id)
            now = datetime.now(UTC)
            if config is None:
                tx.add(
                    BurstGroupingRow(
                        session_id=session_id,
                        gap_seconds=gap_seconds,
                        method_version=BURST_METHOD,
                        input_sha256=fingerprint,
                        grouped_at=now,
                    )
                )
            else:
                config.gap_seconds, config.method_version = gap_seconds, BURST_METHOD
                config.input_sha256, config.grouped_at = fingerprint, now
            tx.flush()
            return _read(tx, session_id)
