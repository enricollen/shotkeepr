"""Repository per aggregato (if-022) — mappatura dominio ↔ righe relazionali."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.models import (
    ExcludedFileRow,
    ImageFileRow,
    SessionRow,
    ShotRow,
)
from shotkeepr.core.domain.catalog import (
    ExcludedFile,
    ExclusionReason,
    FileKind,
    ImageFile,
    Session,
    SessionStatus,
    Shot,
    ShotMetadata,
)
from shotkeepr.core.domain.catalog.ingestion import CatalogImportError


def _session_to_domain(row: SessionRow) -> Session:
    return Session(
        session_id=row.id,
        source_folder=Path(row.source_folder),
        include_subfolders=row.include_subfolders,
        profile_id=row.profile_id,
        status=SessionStatus(row.status),
        checkpoint=row.checkpoint,
        started_at=row.started_at,
        excluded=[
            ExcludedFile(Path(e.path), ExclusionReason(e.reason), e.detail) for e in row.excluded
        ],
    )


def _excluded_rows(session: Session) -> list[ExcludedFileRow]:
    return [
        ExcludedFileRow(path=str(e.path), reason=e.reason.value, detail=e.detail)
        for e in session.excluded
    ]


class SqlSessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, session: Session) -> None:
        with self._db.transaction() as tx:
            tx.add(
                SessionRow(
                    id=session.session_id,
                    source_folder=str(session.source_folder),
                    include_subfolders=session.include_subfolders,
                    profile_id=session.profile_id,
                    status=session.status.value,
                    checkpoint=session.checkpoint,
                    started_at=session.started_at,
                    excluded=_excluded_rows(session),
                )
            )

    def get(self, session_id: uuid.UUID) -> Session | None:
        with self._db.transaction() as tx:
            row = tx.get(SessionRow, session_id)
            return None if row is None else _session_to_domain(row)

    def list(self) -> Sequence[Session]:
        with self._db.transaction() as tx:
            rows = tx.scalars(select(SessionRow).order_by(SessionRow.started_at)).all()
            return [_session_to_domain(r) for r in rows]

    def update(self, session: Session) -> None:
        with self._db.transaction() as tx:
            row = tx.get(SessionRow, session.session_id)
            if row is None:
                raise KeyError(session.session_id)
            row.status = session.status.value
            row.checkpoint = session.checkpoint
            row.profile_id = session.profile_id
            row.include_subfolders = session.include_subfolders
            row.excluded = _excluded_rows(session)


def _file_to_row(f: ImageFile) -> ImageFileRow:
    m = f.metadata
    return ImageFileRow(
        id=f.file_id,
        path=str(f.path),
        format=f.format,
        kind=f.kind.value,
        size=f.size,
        fingerprint=f.fingerprint,
        camera_model=m.camera_model,
        camera_serial=m.camera_serial,
        lens=m.lens,
        focal_mm=m.focal_mm,
        exposure_s=m.exposure_s,
        aperture=m.aperture,
        iso=m.iso,
        capture_time=m.capture_time,
    )


def _file_to_domain(r: ImageFileRow) -> ImageFile:
    return ImageFile(
        file_id=r.id,
        path=Path(r.path),
        format=r.format,
        kind=FileKind(r.kind),
        size=r.size,
        fingerprint=r.fingerprint,
        metadata=ShotMetadata(
            camera_model=r.camera_model,
            camera_serial=r.camera_serial,
            lens=r.lens,
            focal_mm=r.focal_mm,
            exposure_s=r.exposure_s,
            aperture=r.aperture,
            iso=r.iso,
            capture_time=r.capture_time,
        ),
    )


def _shot_to_domain(row: ShotRow) -> Shot:
    return Shot(
        shot_id=row.id,
        session_id=row.session_id,
        content_hash=row.content_hash,
        capture_time=row.capture_time,
        group_id=row.group_id,
        files=[_file_to_domain(f) for f in row.files],
    )


def _shot_to_row(shot: Shot) -> ShotRow:
    return ShotRow(
        id=shot.shot_id,
        session_id=shot.session_id,
        content_hash=shot.content_hash,
        capture_time=shot.capture_time,
        group_id=shot.group_id,
        files=[_file_to_row(file) for file in shot.files],
    )


class SqlShotRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add_many(self, shots: Sequence[Shot]) -> None:
        with self._db.transaction() as tx:
            tx.add_all(_shot_to_row(shot) for shot in shots)

    def get(self, shot_id: uuid.UUID) -> Shot | None:
        with self._db.transaction() as tx:
            row = tx.get(ShotRow, shot_id)
            return None if row is None else _shot_to_domain(row)

    def list_by_session(
        self,
        session_id: uuid.UUID,
        *,
        limit: int | None = None,
        offset: int = 0,
        group_id: uuid.UUID | None = None,
        ungrouped: bool = False,
    ) -> Sequence[Shot]:
        if group_id is not None and ungrouped:
            raise ValueError("filtro gruppo e senza gruppo non combinabili")
        if offset < 0 or (limit is not None and limit < 1):
            raise ValueError("paginazione degli scatti non valida")
        with self._db.transaction() as tx:
            stmt = (
                select(ShotRow)
                .where(ShotRow.session_id == session_id)
                .order_by(ShotRow.capture_time, ShotRow.id)
                .limit(limit)
                .offset(offset)
            )
            if group_id is not None:
                stmt = stmt.where(ShotRow.group_id == group_id)
            elif ungrouped:
                stmt = stmt.where(ShotRow.group_id.is_(None))
            return [_shot_to_domain(r) for r in tx.scalars(stmt).all()]

    def count_by_session(
        self, session_id: uuid.UUID, *, group_id: uuid.UUID | None = None, ungrouped: bool = False
    ) -> int:
        if group_id is not None and ungrouped:
            raise ValueError("filtro gruppo e senza gruppo non combinabili")
        with self._db.transaction() as tx:
            statement = (
                select(func.count()).select_from(ShotRow).where(ShotRow.session_id == session_id)
            )
            if group_id is not None:
                statement = statement.where(ShotRow.group_id == group_id)
            elif ungrouped:
                statement = statement.where(ShotRow.group_id.is_(None))
            return int(tx.scalar(statement) or 0)

    def find_by_hash(self, session_id: uuid.UUID, content_hash: str) -> Shot | None:
        with self._db.transaction() as tx:
            stmt = select(ShotRow).where(
                ShotRow.session_id == session_id, ShotRow.content_hash == content_hash
            )
            row = tx.scalars(stmt).one_or_none()
            return None if row is None else _shot_to_domain(row)


class SqlCatalogWriter:
    """Pubblica scatti, esclusioni e stato della sessione nella stessa transazione."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def validate_destination(self, source: Path) -> None:
        database = self._db.engine.url.database
        if (
            database is not None
            and database != ":memory:"
            and Path(database).resolve().is_relative_to(source.resolve())
        ):
            raise CatalogImportError("il database deve essere esterno alla cartella sorgente")

    def save_import(self, session: Session, shots: Sequence[Shot]) -> None:
        if session.status is not SessionStatus.IMPORTED:
            raise CatalogImportError("solo una sessione importata puo' essere pubblicata")
        if any(shot.session_id != session.session_id for shot in shots):
            raise CatalogImportError("uno scatto appartiene a una sessione diversa")
        self.validate_destination(session.source_folder)
        try:
            with self._db.transaction() as tx:
                row = tx.get(SessionRow, session.session_id)
                if row is None or row.status != SessionStatus.IMPORTING.value:
                    raise CatalogImportError("sessione non presente o non in importazione")
                tx.add_all(_shot_to_row(shot) for shot in shots)
                row.excluded = _excluded_rows(session)
                row.checkpoint = session.checkpoint
                row.status = session.status.value
        except SQLAlchemyError as exc:
            raise CatalogImportError("salvataggio del catalogo non riuscito") from exc
