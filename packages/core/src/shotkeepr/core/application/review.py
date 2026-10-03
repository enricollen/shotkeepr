"""Persistent human decisions and explicit, non-destructive sidecar delivery."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from shotkeepr.core.application.ports import (
    ReviewRepository,
    SessionRepository,
    ShotRepository,
    XmpWriter,
)
from shotkeepr.core.domain.catalog import SessionStatus, Shot
from shotkeepr.core.domain.catalog.review import (
    ReviewError,
    ReviewShotNotFoundError,
    ReviewStatus,
    ShotReview,
    XmpExportItem,
)


def _validate_scope(shot: Shot, folder: Path) -> None:
    if (
        not folder.is_absolute()
        or ".." in folder.parts
        or any(
            not file.path.is_absolute()
            or ".." in file.path.parts
            or not file.path.is_relative_to(folder)
            for file in shot.files
        )
    ):
        raise ReviewError("File esterno alla cartella sorgente della sessione")


class ReviewService:
    def __init__(
        self,
        shots: ShotRepository,
        sessions: SessionRepository,
        reviews: ReviewRepository,
        writer: XmpWriter,
    ) -> None:
        self.shots, self.sessions, self.reviews, self.writer = shots, sessions, reviews, writer

    def _shot(self, shot_id: uuid.UUID) -> Shot:
        shot = self.shots.get(shot_id)
        if shot is None:
            raise ReviewShotNotFoundError("Scatto non presente nel catalogo")
        session = self.sessions.get(shot.session_id)
        if session is None:
            raise ReviewShotNotFoundError("Sessione non presente nel catalogo")
        if session.status in {
            SessionStatus.CREATED,
            SessionStatus.IMPORTING,
            SessionStatus.ANALYZING,
        }:
            raise ReviewError("Attendere la fine dell'elaborazione della sessione")
        return shot

    def get(self, shot_id: uuid.UUID) -> ShotReview:
        self._shot(shot_id)
        return self.reviews.get(shot_id) or ShotReview(shot_id)

    def set_status(self, shot_id: uuid.UUID, status: ReviewStatus) -> ShotReview:
        return self.reviews.set_status(self._shot(shot_id), status)

    def targets(self, shot_id: uuid.UUID) -> Sequence[Path]:
        shot = self._shot(shot_id)
        session = self.sessions.get(shot.session_id)
        if session is None:
            raise ReviewShotNotFoundError("Sessione non presente nel catalogo")
        _validate_scope(shot, session.source_folder)
        keys = {str(file.path.with_suffix(".xmp")).casefold() for file in shot.files}
        for other in self.shots.list_by_session(shot.session_id):
            if other.shot_id != shot_id and any(
                str(file.path.with_suffix(".xmp")).casefold() in keys for file in other.files
            ):
                raise ReviewError("Sidecar condiviso da scatti distinti: export ambiguo rifiutato")
        return self.writer.targets(shot)

    def export(self, shot_id: uuid.UUID, expected_status: ReviewStatus) -> Sequence[Path]:
        shot = self._shot(shot_id)
        review = self.get(shot_id)
        if review.status is not expected_status:
            raise ReviewError("Stato modificato: ricaricare lo scatto prima di esportare")
        self.targets(shot_id)
        return self.writer.write(shot, review)

    def export_session(
        self,
        session_id: uuid.UUID,
        *,
        write: bool = False,
        progress: Callable[[int, int, Sequence[Path]], None] | None = None,
    ) -> Sequence[XmpExportItem]:
        session = self.sessions.get(session_id)
        if session is None:
            raise ReviewShotNotFoundError("Sessione non presente nel catalogo")
        if session.status in {
            SessionStatus.CREATED,
            SessionStatus.IMPORTING,
            SessionStatus.ANALYZING,
        }:
            raise ReviewError("Attendere la fine dell'elaborazione della sessione")
        shots = self.shots.list_by_session(session_id)
        owners: dict[str, uuid.UUID] = {}
        reviews = self.reviews.get_many([shot.shot_id for shot in shots])
        plan: list[XmpExportItem] = []
        for shot in shots:
            _validate_scope(shot, session.source_folder)
            for file in shot.files:
                key = str(file.path.with_suffix(".xmp")).casefold()
                if key in owners and owners[key] != shot.shot_id:
                    raise ReviewError(
                        "Sidecar condiviso da scatti distinti: export ambiguo rifiutato"
                    )
                owners[key] = shot.shot_id
            plan.append(
                XmpExportItem(
                    shot.shot_id,
                    reviews.get(shot.shot_id, ShotReview(shot.shot_id)).status,
                    tuple(self.writer.targets(shot)),
                )
            )
        if write:
            for index, item in enumerate(plan, start=1):
                shot = self._shot(item.shot_id)
                current = self.reviews.get(item.shot_id) or ShotReview(item.shot_id)
                if current.status is not item.status:
                    raise ReviewError(
                        "Revisione modificata durante l'export: ripianificare la sessione"
                    )
                if tuple(self.writer.targets(shot)) != item.paths:
                    raise ReviewError("Percorsi sidecar modificati: ripianificare la sessione")
                paths = self.writer.write(shot, current)
                if progress is not None:
                    progress(index, len(plan), paths)
        return plan
