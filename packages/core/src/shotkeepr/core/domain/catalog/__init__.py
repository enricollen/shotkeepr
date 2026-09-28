"""Catalogo e ingestione (ctx-001): sessioni, scatti, file immagine, file esclusi."""

from shotkeepr.core.domain.catalog.model import (
    ExcludedFile,
    ExclusionReason,
    FileKind,
    ImageFile,
    Session,
    SessionStatus,
    Shot,
    ShotMetadata,
)

__all__ = [
    "ExcludedFile",
    "ExclusionReason",
    "FileKind",
    "ImageFile",
    "Session",
    "SessionStatus",
    "Shot",
    "ShotMetadata",
]
