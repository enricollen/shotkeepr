"""Schema relazionale (ent-001…ent-020). Fonte di verità dello stato applicativo (ADR-005)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UtcDateTime(TypeDecorator[datetime]):
    """Datetime sempre in UTC: SQLite non conserva il fuso orario."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime senza fuso orario")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


TS = UtcDateTime()


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}  # noqa: RUF012


class ProfileRow(Base):
    __tablename__ = "profiles"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    genre: Mapped[str | None] = mapped_column(String(60))
    settings: Mapped[dict[str, Any]]
    criteria: Mapped[list[Any]]


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source_folder: Mapped[str] = mapped_column(String(4096))
    include_subfolders: Mapped[bool] = mapped_column(Boolean, default=True)
    profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("profiles.id"))
    status: Mapped[str] = mapped_column(String(16))
    checkpoint: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(TS)
    excluded: Mapped[list[ExcludedFileRow]] = relationship(
        cascade="all, delete-orphan", order_by="ExcludedFileRow.id"
    )


class ExcludedFileRow(Base):
    __tablename__ = "excluded_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(4096))
    reason: Mapped[str] = mapped_column(String(16))
    detail: Mapped[str] = mapped_column(String(1024), default="")


class GroupRow(Base):
    __tablename__ = "shot_groups"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)


class ShotRow(Base):
    __tablename__ = "shots"
    __table_args__ = (UniqueConstraint("session_id", "content_hash"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    content_hash: Mapped[str] = mapped_column(String(128))
    capture_time: Mapped[datetime | None] = mapped_column(TS)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shot_groups.id", ondelete="SET NULL"), index=True
    )
    files: Mapped[list[ImageFileRow]] = relationship(
        cascade="all, delete-orphan", order_by="ImageFileRow.path"
    )


class ImageFileRow(Base):
    __tablename__ = "image_files"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    shot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(4096))
    format: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    size: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(128))
    camera_model: Mapped[str | None] = mapped_column(String(120))
    camera_serial: Mapped[str | None] = mapped_column(String(120))
    lens: Mapped[str | None] = mapped_column(String(200))
    focal_mm: Mapped[float | None] = mapped_column(Float)
    exposure_s: Mapped[float | None] = mapped_column(Float)
    aperture: Mapped[float | None] = mapped_column(Float)
    iso: Mapped[int | None] = mapped_column(Integer)
    capture_time: Mapped[datetime | None] = mapped_column(TS)


class AnalysisResultRow(Base):
    __tablename__ = "analysis_results"
    shot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), primary_key=True
    )
    analyzer_versions: Mapped[dict[str, Any]]
    status: Mapped[str] = mapped_column(String(16))
    analyzed_at: Mapped[datetime] = mapped_column(TS)
    focus: Mapped[float | None] = mapped_column(Float)
    blur: Mapped[float | None] = mapped_column(Float)
    blur_type: Mapped[str | None] = mapped_column(String(16))
    exposure: Mapped[float | None] = mapped_column(Float)
    highlights_clipped: Mapped[float | None] = mapped_column(Float)
    shadows_clipped: Mapped[float | None] = mapped_column(Float)
    noise: Mapped[float | None] = mapped_column(Float)
    aesthetic: Mapped[float | None] = mapped_column(Float)


class SubjectRow(Base):
    __tablename__ = "subjects"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    shot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_results.shot_id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    bbox: Mapped[list[Any]]
    head_bbox: Mapped[list[Any] | None] = mapped_column(JSON)
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float)
    eyes_open: Mapped[bool | None] = mapped_column(Boolean)
    eyes_visible: Mapped[bool | None] = mapped_column(Boolean)
    eyes_in_focus: Mapped[bool | None] = mapped_column(Boolean)
    eyes_confidence: Mapped[float | None] = mapped_column(Float)


class GroupCorrectionRow(Base):
    __tablename__ = "group_corrections"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(8))
    shot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    from_group: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    to_group: Mapped[uuid.UUID] = mapped_column(Uuid)
    at: Mapped[datetime] = mapped_column(TS)


class SelectionRunRow(Base):
    __tablename__ = "selection_runs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    settings_snapshot: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(TS)
    acceptance_rate: Mapped[float | None] = mapped_column(Float)


class DecisionRow(Base):
    __tablename__ = "decisions"
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("selection_runs.id", ondelete="CASCADE"), primary_key=True
    )
    shot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(8))
    overall_score: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(String(8))
    reasons: Mapped[list[Any]]


class ManualStatusChangeRow(Base):
    __tablename__ = "manual_status_changes"
    __table_args__ = (Index("ix_manual_status_changes_session_shot", "session_id", "shot_id"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    shot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"))
    old_status: Mapped[str] = mapped_column(String(8))
    new_status: Mapped[str] = mapped_column(String(8))
    at: Mapped[datetime] = mapped_column(TS)


class AppSettingsRow(Base):
    """ent-029 — riga unica con le preferenze serializzate (mai credenziali)."""

    __tablename__ = "app_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict[str, Any]]
    updated_at: Mapped[datetime] = mapped_column(TS)
