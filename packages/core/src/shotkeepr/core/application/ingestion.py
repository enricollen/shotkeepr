"""Importazione headless con esclusioni per file e persistenza atomica del catalogo."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shotkeepr.core.application.ports import (
    CatalogWriter,
    PhotoSource,
    PreviewStore,
    SessionRepository,
)
from shotkeepr.core.domain.catalog import ExcludedFile, ImageFile, Session, SessionStatus, Shot
from shotkeepr.core.domain.catalog.ingestion import (
    CatalogImportError,
    FileInspectionError,
    ImportCancelledError,
    build_shots,
)


@dataclass(frozen=True, slots=True)
class ImportProgress:
    processed: int
    imported: int
    excluded: int
    path: Path


@dataclass(frozen=True, slots=True)
class ImportResult:
    session: Session
    shots: tuple[Shot, ...]


class PhotoImportService:
    def __init__(
        self,
        source: PhotoSource,
        previews: PreviewStore,
        sessions: SessionRepository,
        writer: CatalogWriter,
    ) -> None:
        self._source = source
        self._previews = previews
        self._sessions = sessions
        self._writer = writer

    def import_folder(
        self,
        folder: Path,
        *,
        recursive: bool = True,
        progress: Callable[[ImportProgress], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        session_id: uuid.UUID | None = None,
    ) -> ImportResult:
        def check_cancelled() -> None:
            if cancelled is not None and cancelled():
                raise ImportCancelledError("Importazione annullata")

        check_cancelled()
        root = self._source.validate_folder(folder)
        self._previews.validate_destination(root)
        self._writer.validate_destination(root)
        session = Session(
            source_folder=root,
            include_subfolders=recursive,
            status=SessionStatus.IMPORTING,
            session_id=session_id if session_id is not None else uuid.uuid4(),
        )
        self._sessions.add(session)
        files: list[ImageFile] = []
        try:
            for item in self._source.scan(root, recursive=recursive):
                check_cancelled()
                if isinstance(item, ExcludedFile):
                    session.excluded.append(item)
                    path = item.path
                else:
                    path = item
                    try:
                        file = self._source.inspect(item)
                        self._previews.create(file)
                        files.append(file)
                    except FileInspectionError as exc:
                        session.excluded.append(ExcludedFile(item, exc.reason, str(exc)))
                session.checkpoint += 1
                if progress is not None:
                    progress(
                        ImportProgress(session.checkpoint, len(files), len(session.excluded), path)
                    )
            check_cancelled()
            shots = build_shots(session.session_id, files)
            check_cancelled()
            session.status = SessionStatus.IMPORTED
            self._writer.save_import(session, shots)
        except ImportCancelledError:
            session.status = SessionStatus.CANCELLED
            self._sessions.update(session)
            raise
        except (CatalogImportError, OSError):
            session.status = SessionStatus.FAILED
            self._sessions.update(session)
            raise
        return ImportResult(session, tuple(shots))
