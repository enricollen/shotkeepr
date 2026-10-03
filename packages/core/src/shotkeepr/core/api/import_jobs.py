"""Importazione in background con stato recuperabile e arresto cooperativo."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.api.events import Event, EventBus, EventKind
from shotkeepr.core.api.photo_schemas import ImportJobOut, ImportJobStatus
from shotkeepr.core.application.ingestion import ImportProgress, ImportResult, PhotoImportService
from shotkeepr.core.application.ports import PreviewStore, SessionRepository, ShotRepository
from shotkeepr.core.domain.catalog.ingestion import CatalogImportError, ImportCancelledError

logger = logging.getLogger(__name__)
MAX_RETAINED_JOBS = 20


class ImportBusyError(CatalogImportError):
    """Un'importazione e' gia' attiva oppure il nucleo si sta arrestando."""


@dataclass(slots=True)
class _Job:
    snapshot: ImportJobOut
    cancelled: threading.Event = field(default_factory=threading.Event)
    last_event: float = 0.0


class ImportJobs:
    def __init__(
        self,
        factory: Callable[[], PhotoImportService],
        sessions: SessionRepository,
        shots: ShotRepository,
        previews: PreviewStore,
    ) -> None:
        self._factory = factory
        self.sessions = sessions
        self.shots = shots
        self.previews = previews
        self.events = EventBus()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="shotkeepr-import")
        self._lock = threading.Lock()
        self._jobs: dict[uuid.UUID, _Job] = {}
        self._active: uuid.UUID | None = None
        self._closing = False

    def start(self, folder: Path, *, recursive: bool) -> ImportJobOut:
        with self._lock:
            if self._closing or self._active is not None:
                raise ImportBusyError(
                    "Un'importazione e' gia' attiva oppure il nucleo si sta arrestando"
                )
            # ExifTool viene verificato quando serve, non all'avvio dell'API.
            service = self._factory()
            if not folder.is_absolute():
                raise CatalogImportError("usare un percorso assoluto nel filesystem del nucleo")
            job = _Job(
                ImportJobOut(
                    job_id=uuid.uuid4(), session_id=uuid.uuid4(), source_folder=str(folder)
                )
            )
            self._jobs[job.snapshot.job_id] = job
            self._active = job.snapshot.job_id
            while len(self._jobs) > MAX_RETAINED_JOBS:
                del self._jobs[next(iter(self._jobs))]
            future = self._executor.submit(self._run, job, service, folder, recursive)
            snapshot = job.snapshot.model_copy(deep=True)
        future.add_done_callback(lambda completed: self._complete(job, completed))
        return snapshot

    def get(self, job_id: uuid.UUID) -> ImportJobOut:
        with self._lock:
            return self._jobs[job_id].snapshot.model_copy(deep=True)

    def cancel(self, job_id: uuid.UUID) -> ImportJobOut:
        with self._lock:
            job = self._jobs[job_id]
            if job.snapshot.status in {ImportJobStatus.QUEUED, ImportJobStatus.RUNNING}:
                job.cancelled.set()
                job.snapshot.cancel_requested = True
            return job.snapshot.model_copy(deep=True)

    def _run(
        self, job: _Job, service: PhotoImportService, folder: Path, recursive: bool
    ) -> ImportResult:
        with self._lock:
            job.snapshot.status = ImportJobStatus.RUNNING
        return service.import_folder(
            folder,
            recursive=recursive,
            session_id=job.snapshot.session_id,
            progress=lambda progress: self._progress(job, progress),
            cancelled=job.cancelled.is_set,
        )

    def _progress(self, job: _Job, progress: ImportProgress) -> None:
        with self._lock:
            job.snapshot.processed = progress.processed
            job.snapshot.imported_files = progress.imported
            job.snapshot.excluded_files = progress.excluded
            job.snapshot.current_file = progress.path.name
            now = time.monotonic()
            notify = now - job.last_event >= 0.25
            if notify:
                job.last_event = now
            payload = job.snapshot.model_dump(mode="json")
        if notify:
            self.events.publish(Event(EventKind.PROGRESS, {"operation": "photo-import", **payload}))

    def _complete(self, job: _Job, future: Future[ImportResult]) -> None:
        failure = future.exception()
        with self._lock:
            if isinstance(failure, ImportCancelledError):
                job.snapshot.status = ImportJobStatus.CANCELLED
            elif failure is not None:
                job.snapshot.status = ImportJobStatus.FAILED
                job.snapshot.error = (
                    str(failure)
                    if isinstance(failure, (CatalogImportError, OSError))
                    else "Importazione fallita: consultare i log del nucleo"
                )
            else:
                result = future.result()
                job.snapshot.status = ImportJobStatus.SUCCEEDED
                job.snapshot.processed = result.session.checkpoint
                job.snapshot.shots = len(result.shots)
                job.snapshot.imported_files = sum(len(shot.files) for shot in result.shots)
                job.snapshot.excluded_files = len(result.session.excluded)
            self._active = None
            payload = job.snapshot.model_dump(mode="json")
        if failure is not None and not isinstance(failure, ImportCancelledError):
            logger.error(
                "Importazione fotografica fallita",
                exc_info=(type(failure), failure, failure.__traceback__),
            )
            # Un errore inatteso del worker deve comparire anche nel catalogo persistente.
            try:
                session = self.sessions.get(job.snapshot.session_id)
                if session is not None and session.status.value == "IMPORTING":
                    from shotkeepr.core.domain.catalog import SessionStatus  # noqa: PLC0415

                    session.status = SessionStatus.FAILED
                    self.sessions.update(session)
            except SQLAlchemyError:
                logger.exception("Impossibile aggiornare la sessione fallita")
        self.events.publish(Event(EventKind.NOTIFICATION, {"operation": "photo-import", **payload}))

    def shutdown(self) -> None:
        with self._lock:
            self._closing = True
            if self._active is not None:
                self._jobs[self._active].cancelled.set()
        self._executor.shutdown(wait=True)
