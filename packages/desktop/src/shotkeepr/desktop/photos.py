"""Importazioni e anteprime via client generato, fuori dal thread grafico."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

import httpx
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from shotkeepr.desktop.api_client import AuthenticatedClient
from shotkeepr.desktop.api_client.api.photos import (
    cancel_photo_import,
    export_photo_xmp,
    get_photo_import,
    get_photo_session,
    get_photo_thumbnail,
    group_photo_bursts,
    list_photo_sessions,
    list_photo_shots,
    measure_photo_exposure,
    measure_photo_sharpness,
    set_photo_review,
    start_photo_import,
)
from shotkeepr.desktop.api_client.errors import UnexpectedStatus
from shotkeepr.desktop.api_client.models import (
    ApiError,
    BurstGroupingOut,
    BurstRequest,
    ExposureOut,
    ImportJobOut,
    ImportJobStatus,
    ImportRequest,
    ReviewOut,
    ReviewRequest,
    ReviewStatus,
    SessionOut,
    SessionStatus,
    SharpnessOut,
    ShotOut,
    ShotPageOut,
    XmpOut,
    XmpRequest,
)
from shotkeepr.desktop.api_client.types import File

PAGE_SIZE = 40


class Operation(StrEnum):
    START = "start"
    POLL = "poll"
    CANCEL = "cancel"
    PAGE = "page"
    SESSIONS = "sessions"
    EXPOSURE = "exposure"
    SHARPNESS = "sharpness"
    REVIEW = "review"
    XMP = "xmp"
    GROUP = "group"
    MEASURE_SESSION = "measure-session"
    EXPORT_SESSION = "export-session"


class PhotoRequestError(RuntimeError):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def _expect[T](value: object, expected: type[T], status: int) -> T:
    if isinstance(value, ApiError):
        raise PhotoRequestError(value.detail, status)
    if not isinstance(value, expected):
        raise ValueError("Risposta del catalogo non compatibile")
    return value


@dataclass(frozen=True, slots=True)
class Thumbnail:
    shot: ShotOut
    content: bytes | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PhotoPage:
    session: SessionOut
    page: ShotPageOut
    thumbnails: tuple[Thumbnail, ...]
    group_id: uuid.UUID | None = None
    ungrouped: bool = False


@dataclass(frozen=True, slots=True)
class PhotoSessions:
    items: tuple[SessionOut, ...]


@dataclass(frozen=True, slots=True)
class PreviewBatch:
    session_id: uuid.UUID
    completed: int
    total: int
    cancelled: bool


@dataclass(frozen=True, slots=True)
class XmpBatch:
    session_id: uuid.UUID
    completed: int
    total: int
    paths: int
    cancelled: bool


type PhotoResult = (
    ImportJobOut
    | PhotoPage
    | PhotoSessions
    | ExposureOut
    | ReviewOut
    | XmpOut
    | BurstGroupingOut
    | SharpnessOut
    | PreviewBatch
    | XmpBatch
)


class PhotoWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str, int)
    measurement_received = Signal(object)
    measurement_progress = Signal(int, int)
    xmp_progress = Signal(int, int)

    def __init__(
        self,
        url: str,
        token: str,
        operation: Operation,
        parent: QObject,
        *,
        target: uuid.UUID | None = None,
        folder: str = "",
        recursive: bool = True,
        offset: int = 0,
        review_status: ReviewStatus | None = None,
        gap_seconds: float = 2.0,
        group_id: uuid.UUID | None = None,
        ungrouped: bool = False,
    ) -> None:
        super().__init__(parent)
        self.operation = operation
        self._url, self._token = url, token
        self._target, self._folder = target, folder
        self._recursive, self._offset = recursive, offset
        self._review_status = review_status
        self._gap_seconds, self._group_id, self._ungrouped = gap_seconds, group_id, ungrouped
        self._batch_completed = 0
        self._batch_total = 0
        self._batch_paths = 0

    def _page(self, client: AuthenticatedClient, target: uuid.UUID) -> PhotoPage:
        response = get_photo_session.sync_detailed(target, client=client)
        session = _expect(response.parsed, SessionOut, response.status_code)
        if session.status in {SessionStatus.IMPORTING, SessionStatus.ANALYZING}:
            raise PhotoRequestError("Questa sessione e' ancora in elaborazione.", 409)
        page_response = list_photo_shots.sync_detailed(
            target,
            client=client,
            limit=PAGE_SIZE,
            offset=self._offset,
            group_id=self._group_id,
            ungrouped=self._ungrouped,
        )
        page = _expect(page_response.parsed, ShotPageOut, page_response.status_code)
        thumbnails: list[Thumbnail] = []
        for shot in page.items:
            if self.isInterruptionRequested():
                raise PhotoRequestError("Caricamento anteprime interrotto")
            preview = get_photo_thumbnail.sync_detailed(shot.shot_id, client=client)
            if isinstance(preview.parsed, ApiError) and preview.status_code == 404:
                thumbnails.append(Thumbnail(shot, None, preview.parsed.detail))
            else:
                _expect(preview.parsed, File, preview.status_code)
                thumbnails.append(Thumbnail(shot, preview.content))
        return PhotoPage(session, page, tuple(thumbnails), self._group_id, self._ungrouped)

    def _sessions(self, client: AuthenticatedClient) -> PhotoSessions:
        response = list_photo_sessions.sync_detailed(client=client)
        if isinstance(response.parsed, ApiError):
            raise PhotoRequestError(response.parsed.detail, response.status_code)
        if not isinstance(response.parsed, list):
            raise ValueError("Elenco delle sessioni non compatibile")
        sessions: list[SessionOut] = []
        for session in response.parsed:
            sessions.append(_expect(session, SessionOut, response.status_code))
        sessions.sort(key=lambda item: (item.started_at, item.session_id.int), reverse=True)
        return PhotoSessions(tuple(sessions))

    def _perform(self, client: AuthenticatedClient) -> PhotoResult:
        if self.operation is Operation.SESSIONS:
            return self._sessions(client)
        if self.operation is Operation.START:
            started = start_photo_import.sync_detailed(
                client=client,
                body=ImportRequest(source_folder=self._folder, include_subfolders=self._recursive),
            )
            return _expect(started.parsed, ImportJobOut, started.status_code)
        if self._target is None:
            raise ValueError("Identificativo del catalogo mancante")
        if self.operation in {
            Operation.REVIEW,
            Operation.XMP,
            Operation.EXPOSURE,
            Operation.SHARPNESS,
        }:
            return self._shot_result(client, self._target)
        if self.operation in {
            Operation.PAGE,
            Operation.GROUP,
            Operation.MEASURE_SESSION,
            Operation.EXPORT_SESSION,
        }:
            return self._session_result(client, self._target)
        if self.operation is Operation.CANCEL:
            cancelled = cancel_photo_import.sync_detailed(self._target, client=client)
            return _expect(cancelled.parsed, ImportJobOut, cancelled.status_code)
        polled = get_photo_import.sync_detailed(self._target, client=client)
        return _expect(polled.parsed, ImportJobOut, polled.status_code)

    def _session_result(
        self, client: AuthenticatedClient, target: uuid.UUID
    ) -> PhotoPage | BurstGroupingOut | PreviewBatch | XmpBatch:
        if self.operation in {Operation.MEASURE_SESSION, Operation.EXPORT_SESSION}:
            return self._process_session(client, target)
        if self.operation is Operation.GROUP:
            grouped = group_photo_bursts.sync_detailed(
                target, client=client, body=BurstRequest(gap_seconds=self._gap_seconds)
            )
            return _expect(grouped.parsed, BurstGroupingOut, grouped.status_code)
        return self._page(client, target)

    def _shot_result(
        self, client: AuthenticatedClient, target: uuid.UUID
    ) -> ExposureOut | SharpnessOut | ReviewOut | XmpOut:
        if self.operation is Operation.EXPOSURE:
            measured = measure_photo_exposure.sync_detailed(target, client=client)
            return _expect(measured.parsed, ExposureOut, measured.status_code)
        if self.operation is Operation.SHARPNESS:
            detailed = measure_photo_sharpness.sync_detailed(target, client=client)
            return _expect(detailed.parsed, SharpnessOut, detailed.status_code)
        if self._review_status is None:
            raise ValueError("Stato della revisione mancante")
        if self.operation is Operation.REVIEW:
            saved = set_photo_review.sync_detailed(
                target, client=client, body=ReviewRequest(status=self._review_status)
            )
            return _expect(saved.parsed, ReviewOut, saved.status_code)
        return self._export(client, target, self._review_status)

    @staticmethod
    def _export(client: AuthenticatedClient, target: uuid.UUID, status: ReviewStatus) -> XmpOut:
        response = export_photo_xmp.sync_detailed(
            target, client=client, body=XmpRequest(confirm=True, expected_status=status)
        )
        result = _expect(response.parsed, XmpOut, response.status_code)
        if (
            result.shot_id != target
            or result.status is not status
            or not isinstance(result.paths, list)
            or not result.paths
            or any(not isinstance(path, str) or not path.strip() for path in result.paths)
            or len(set(result.paths)) != len(result.paths)
        ):
            raise ValueError("Risultato dell'export non compatibile")
        return result

    def _process_session(
        self, client: AuthenticatedClient, target: uuid.UUID
    ) -> PreviewBatch | XmpBatch:
        response = get_photo_session.sync_detailed(target, client=client)
        session = _expect(response.parsed, SessionOut, response.status_code)
        if session.session_id != target or session.shots < 0:
            raise ValueError("Sessione del catalogo non compatibile")
        if session.status not in {SessionStatus.IMPORTED, SessionStatus.ANALYZED}:
            raise PhotoRequestError(
                "Operazione consentita solo su sessioni importate o analizzate.", 409
            )
        self._batch_total = session.shots
        self._batch_progress()
        seen: set[uuid.UUID] = set()
        while self._batch_completed < self._batch_total and not self.isInterruptionRequested():
            page_response = list_photo_shots.sync_detailed(
                target, client=client, limit=PAGE_SIZE, offset=self._batch_completed
            )
            page = _expect(page_response.parsed, ShotPageOut, page_response.status_code)
            self._validate_batch_page(page, seen)
            for shot in page.items:
                completed = (
                    self._export_batch_shot(client, shot)
                    if self.operation is Operation.EXPORT_SESSION
                    else self._measure_batch_shot(client, shot.shot_id)
                )
                if not completed:
                    break
                self._batch_completed += 1
                self._batch_progress()
        cancelled = self.isInterruptionRequested() and self._batch_completed < self._batch_total
        if self.operation is Operation.EXPORT_SESSION:
            return XmpBatch(
                target, self._batch_completed, self._batch_total, self._batch_paths, cancelled
            )
        return PreviewBatch(target, self._batch_completed, self._batch_total, cancelled)

    def _batch_progress(self) -> None:
        signal = (
            self.xmp_progress
            if self.operation is Operation.EXPORT_SESSION
            else self.measurement_progress
        )
        signal.emit(self._batch_completed, self._batch_total)

    def _validate_batch_page(self, page: ShotPageOut, seen: set[uuid.UUID]) -> None:
        ids = {shot.shot_id for shot in page.items}
        if (
            page.offset != self._batch_completed
            or page.total != self._batch_total
            or not page.items
            or len(page.items) > min(PAGE_SIZE, self._batch_total - self._batch_completed)
            or len(ids) != len(page.items)
            or ids & seen
        ):
            raise ValueError("Paginazione della sessione non compatibile")
        seen.update(ids)

    def _measure_batch_shot(self, client: AuthenticatedClient, shot_id: uuid.UUID) -> bool:
        if self.isInterruptionRequested():
            return False
        exposure = measure_photo_exposure.sync_detailed(shot_id, client=client)
        measured = _expect(exposure.parsed, ExposureOut, exposure.status_code)
        if measured.shot_id != shot_id:
            raise ValueError("Misura restituita per uno scatto diverso")
        self.measurement_received.emit(measured)
        if self.isInterruptionRequested():
            return False
        sharpness = measure_photo_sharpness.sync_detailed(shot_id, client=client)
        detailed = _expect(sharpness.parsed, SharpnessOut, sharpness.status_code)
        if detailed.shot_id != shot_id:
            raise ValueError("Misura restituita per uno scatto diverso")
        self.measurement_received.emit(detailed)
        return True

    def _export_batch_shot(self, client: AuthenticatedClient, shot: ShotOut) -> bool:
        if self.isInterruptionRequested():
            return False
        review = shot.review
        if not isinstance(review, ReviewOut) or review.shot_id != shot.shot_id:
            raise ValueError("Revisione salvata dello scatto non compatibile")
        result = self._export(client, shot.shot_id, review.status)
        self._batch_paths += len(result.paths)
        return True

    def _report_failure(self, message: str, status: int) -> None:
        if self.operation is Operation.EXPORT_SESSION:
            message = (
                f"Export interrotto: {self._batch_completed}/{self._batch_total} scatti "
                f"confermati, {self._batch_paths} sidecar. Nessun rollback degli XMP gia' scritti. "
                "Verificare i sidecar nel nucleo prima di riprovare. " + message
            )
        elif self.operation is Operation.MEASURE_SESSION:
            message = (
                f"Misure interrotte: {self._batch_completed}/{self._batch_total} "
                "scatti completati. "
                "Le misure gia' salvate restano disponibili; riavviare per riprendere. " + message
            )
        self.failed.emit(message, status)

    def run(self) -> None:
        try:
            with AuthenticatedClient(
                base_url=self._url,
                token=self._token,
                timeout=httpx.Timeout(
                    60
                    if self.operation in {Operation.XMP, Operation.GROUP, Operation.EXPORT_SESSION}
                    else 3,
                    connect=1,
                ),
                raise_on_unexpected_status=True,
                httpx_args={"trust_env": False},
            ) as client:
                result = self._perform(client)
        except PhotoRequestError as exc:
            self._report_failure(str(exc), exc.status)
        except UnexpectedStatus as exc:
            self._report_failure(f"Errore del nucleo HTTP {exc.status_code}", exc.status_code)
        except httpx.HTTPError:
            message = (
                "Esito export XMP non noto: verifica i sidecar nel nucleo prima di riprovare."
                if self.operation in {Operation.XMP, Operation.EXPORT_SESSION}
                else "Nucleo non raggiungibile. Riprova l'operazione del catalogo."
            )
            self._report_failure(message, 0)
        except (ValueError, TypeError, KeyError):
            self._report_failure(
                "Risposta del catalogo non compatibile con questa applicazione.", 0
            )
        else:
            self.succeeded.emit(result)


class PhotoController(QObject):
    job_updated = Signal(object)
    page_received = Signal(object)
    sessions_received = Signal(object)
    exposure_received = Signal(object)
    sharpness_received = Signal(object)
    review_received = Signal(object)
    xmp_received = Signal(object)
    groups_received = Signal(object)
    measurement_progress = Signal(int, int)
    measurements_finished = Signal(object)
    xmp_progress = Signal(int, int)
    xmp_session_finished = Signal(object)
    failed = Signal(str)
    active_changed = Signal(bool)
    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._url = ""
        self._token = ""
        self._worker: PhotoWorker | None = None
        self._job_id: uuid.UUID | None = None
        self._session_id: uuid.UUID | None = None
        self._active = False
        self._closing = False
        self._cancel_pending = False
        self._page_pending = False
        self._poll_paused = False
        self._offset = 0
        self._sessions_pending = False
        self._group_reload_pending = False
        self._group_refresh_expected = False
        self._view_group_id: uuid.UUID | None = None
        self._view_ungrouped = False
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh_job)

    def configure(self, url: str, token: str) -> None:
        self._url, self._token = url, token

    @property
    def session_id(self) -> uuid.UUID | None:
        return self._session_id

    @property
    def view_group_id(self) -> uuid.UUID | None:
        return self._view_group_id

    @property
    def view_ungrouped(self) -> bool:
        return self._view_ungrouped

    @property
    def measuring_session(self) -> bool:
        return self._worker is not None and self._worker.operation is Operation.MEASURE_SESSION

    @property
    def measurement_cancel_requested(self) -> bool:
        return (
            self.measuring_session
            and self._worker is not None
            and self._worker.isInterruptionRequested()
        )

    @property
    def exporting_session(self) -> bool:
        return self._worker is not None and self._worker.operation is Operation.EXPORT_SESSION

    @property
    def export_cancel_requested(self) -> bool:
        return (
            self.exporting_session
            and self._worker is not None
            and self._worker.isInterruptionRequested()
        )

    def export_session(self) -> None:
        if self._active or self._worker is not None:
            self.failed.emit("Attendere la fine dell'operazione corrente.")
            return
        if not self._url or self._session_id is None:
            self.failed.emit("Aprire una sessione nel nucleo connesso prima di esportare.")
            return
        self._request(Operation.EXPORT_SESSION, target=self._session_id)

    def cancel_session_export(self) -> None:
        if not self.exporting_session:
            self.failed.emit("Nessun export della sessione in corso.")
            return
        if self._worker is not None:
            self._worker.requestInterruption()

    def measure_session(self) -> None:
        if self._active or self._worker is not None:
            self.failed.emit("Attendere la fine dell'operazione corrente.")
            return
        if not self._url or self._session_id is None:
            self.failed.emit("Aprire una sessione nel nucleo connesso prima di misurare.")
            return
        self._request(Operation.MEASURE_SESSION, target=self._session_id)

    def cancel_measurements(self) -> None:
        if not self.measuring_session:
            self.failed.emit("Nessuna misura della sessione in corso.")
            return
        if self._worker is not None:
            self._worker.requestInterruption()

    def refresh_sessions(self) -> None:
        if not self._url:
            self.failed.emit("Il nucleo non e' connesso.")
            return
        if self._active or self._worker is not None:
            self._sessions_pending = True
            return
        self._sessions_pending = False
        self._request(Operation.SESSIONS)

    def open_session(
        self, session_id: uuid.UUID, *, group_id: uuid.UUID | None = None, ungrouped: bool = False
    ) -> None:
        if self._active or self._worker is not None:
            self.failed.emit("Attendere la fine dell'operazione corrente.")
            return
        if not self._url:
            self.failed.emit("Il nucleo non e' connesso.")
            return
        self._request(Operation.PAGE, target=session_id, group_id=group_id, ungrouped=ungrouped)

    def group_bursts(self, gap_seconds: float) -> None:
        if self._active or self._worker is not None:
            self.failed.emit("Attendere la fine dell'operazione corrente.")
            return
        if not self._url or self._session_id is None:
            self.failed.emit("Aprire una sessione nel nucleo connesso prima di raggruppare.")
            return
        self._request(Operation.GROUP, target=self._session_id, gap_seconds=gap_seconds)

    def measure_exposure(self, shot_id: uuid.UUID) -> None:
        self._shot_request(Operation.EXPOSURE, shot_id)

    def measure_sharpness(self, shot_id: uuid.UUID) -> None:
        self._shot_request(Operation.SHARPNESS, shot_id)

    def set_review(self, shot_id: uuid.UUID, status: ReviewStatus) -> None:
        self._shot_request(Operation.REVIEW, shot_id, status)

    def export_xmp(self, shot_id: uuid.UUID, status: ReviewStatus) -> None:
        self._shot_request(Operation.XMP, shot_id, status)

    def _shot_request(
        self, operation: Operation, shot_id: uuid.UUID, status: ReviewStatus | None = None
    ) -> None:
        if self._active or self._worker is not None:
            self.failed.emit("Attendere la fine dell'operazione corrente.")
            return
        if not self._url:
            self.failed.emit("Il nucleo non e' connesso.")
            return
        self._request(operation, target=shot_id, review_status=status)

    def start_import(self, folder: str, recursive: bool) -> None:
        if self._active or self._worker is not None:
            self.failed.emit("Attendere la fine dell'operazione corrente.")
            return
        if not self._url:
            self.failed.emit("Il nucleo non e' connesso.")
            return
        self._job_id, self._session_id = None, None
        self._view_group_id, self._view_ungrouped = None, False
        self._group_reload_pending = False
        self._group_refresh_expected = False
        self._offset = 0
        self._poll_paused = False
        self._active = True
        self.active_changed.emit(True)
        self._request(Operation.START, folder=folder, recursive=recursive)

    def cancel_import(self) -> None:
        if not self._active:
            return
        self._cancel_pending = True
        if self._worker is None and self._job_id is not None:
            self._cancel_pending = False
            self._request(Operation.CANCEL, target=self._job_id)

    def refresh_job(self) -> None:
        if self._active and self._job_id is not None and self._worker is None:
            self._poll_paused = False
            self._request(Operation.POLL, target=self._job_id)

    def load_more(self) -> None:
        if self._worker is None and self._session_id is not None and not self._active:
            self._request(
                Operation.PAGE,
                target=self._session_id,
                offset=self._offset,
                group_id=self._view_group_id,
                ungrouped=self._view_ungrouped,
            )

    def _request(
        self,
        operation: Operation,
        *,
        target: uuid.UUID | None = None,
        folder: str = "",
        recursive: bool = True,
        offset: int = 0,
        review_status: ReviewStatus | None = None,
        gap_seconds: float = 2.0,
        group_id: uuid.UUID | None = None,
        ungrouped: bool = False,
    ) -> None:
        if self._closing:
            return
        worker = PhotoWorker(
            self._url,
            self._token,
            operation,
            self,
            target=target,
            folder=folder,
            recursive=recursive,
            offset=offset,
            review_status=review_status,
            gap_seconds=gap_seconds,
            group_id=group_id,
            ungrouped=ungrouped,
        )
        self._worker = worker
        worker.succeeded.connect(self._success)
        worker.failed.connect(self._failure)
        worker.measurement_received.connect(self._success)
        worker.measurement_progress.connect(self._batch_progress)
        worker.xmp_progress.connect(self._batch_progress)
        worker.finished.connect(self._finished)
        self.busy_changed.emit(True)
        worker.start()

    def _batch_progress(self, completed: int, total: int) -> None:
        if self._closing:
            return
        signal = self.xmp_progress if self.exporting_session else self.measurement_progress
        signal.emit(completed, total)

    def _success(self, result: PhotoResult) -> None:
        if self._closing:
            return
        if isinstance(result, PreviewBatch):
            self.measurements_finished.emit(result)
            return
        if isinstance(result, XmpBatch):
            self.xmp_session_finished.emit(result)
            return
        if isinstance(result, (ReviewOut, XmpOut, ExposureOut, SharpnessOut, BurstGroupingOut)):
            self._catalog_success(result)
            return
        if isinstance(result, PhotoSessions):
            self.sessions_received.emit(result)
            return
        if isinstance(result, PhotoPage):
            self._group_refresh_expected = False
            self._session_id = result.session.session_id
            self._view_group_id, self._view_ungrouped = result.group_id, result.ungrouped
            self._offset = result.page.offset + len(result.page.items)
            self.page_received.emit(result)
            return
        self._job_id = result.job_id
        self._session_id = result.session_id
        self.job_updated.emit(result)
        if result.status in {
            ImportJobStatus.SUCCEEDED,
            ImportJobStatus.FAILED,
            ImportJobStatus.CANCELLED,
        }:
            self._active = False
            self._cancel_pending = False
            self._timer.stop()
            self.active_changed.emit(False)
            if result.status is ImportJobStatus.SUCCEEDED:
                self._offset = 0
                self._page_pending = True
            elif result.status is ImportJobStatus.FAILED:
                self.failed.emit(result.error or "Importazione fallita")

    def _catalog_success(
        self, result: ReviewOut | XmpOut | ExposureOut | SharpnessOut | BurstGroupingOut
    ) -> None:
        if isinstance(result, ReviewOut):
            self.review_received.emit(result)
        elif isinstance(result, XmpOut):
            self.xmp_received.emit(result)
        elif isinstance(result, ExposureOut):
            self.exposure_received.emit(result)
        elif isinstance(result, SharpnessOut):
            self.sharpness_received.emit(result)
        else:
            self.groups_received.emit(result)
            self._group_reload_pending = True

    def _failure(self, message: str, status: int) -> None:
        if self._closing:
            return
        self._timer.stop()
        if self._group_refresh_expected:
            message = (
                "Raffiche salvate, ma ricaricamento non riuscito. Riaprire la sessione. " + message
            )
            self._group_refresh_expected = False
        self._poll_paused = True
        if self._worker is not None and (
            self._worker.operation is Operation.START
            or (self._worker.operation in {Operation.POLL, Operation.CANCEL} and status == 404)
        ):
            self._active = False
            self._job_id = None
            self.active_changed.emit(False)
        self.failed.emit(message)

    def _finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self.busy_changed.emit(False)
        if self._closing:
            return
        if self._cancel_pending and self._job_id is not None:
            self._cancel_pending = False
            self._request(Operation.CANCEL, target=self._job_id)
        elif self._group_reload_pending and self._session_id is not None:
            self._group_reload_pending = False
            self._group_refresh_expected = True
            self.open_session(self._session_id)
        elif self._page_pending and self._session_id is not None:
            self._page_pending = False
            self.load_more()
        elif self._sessions_pending and not self._active:
            self.refresh_sessions()
        elif self._active and self._job_id is not None and not self._poll_paused:
            self._timer.start()

    def shutdown(self) -> None:
        self._closing = True
        self._timer.stop()
        self._poll_paused = True
        if self._worker is not None:
            self._worker.requestInterruption()
            self._worker.wait()
            self._finished()
