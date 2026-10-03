import hashlib
import io
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from shotkeepr.core.adapters.ingestion.previews import PillowRawPreviewStore
from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.migrate import upgrade_to_head
from shotkeepr.core.adapters.persistence.repositories import (
    SqlCatalogWriter,
    SqlSessionRepository,
    SqlShotRepository,
)
from shotkeepr.core.adapters.persistence.settings import SqlSettingsRepository
from shotkeepr.core.adapters.secrets.stores import EnvSecretStore
from shotkeepr.core.api.app import create_app
from shotkeepr.core.api.import_jobs import MAX_RETAINED_JOBS, ImportJobs
from shotkeepr.core.api.photo_schemas import ImportJobStatus
from shotkeepr.core.application.configuration import ConfigurationService
from shotkeepr.core.application.ingestion import PhotoImportService
from shotkeepr.core.domain.catalog import (
    ExcludedFile,
    ExclusionReason,
    FileKind,
    ImageFile,
    SessionStatus,
)
from shotkeepr.core.domain.catalog.ingestion import ExifToolUnavailableError, FileInspectionError

HEADERS = {"Authorization": "Bearer test-photo-token"}


@dataclass
class Source:
    gate: threading.Event | None = None
    entered: threading.Event = field(default_factory=threading.Event)
    failure: Exception | None = None

    def validate_folder(self, folder: Path) -> Path:
        if not folder.is_dir():
            raise FileNotFoundError(str(folder))
        return folder.resolve()

    def scan(self, folder: Path, *, recursive: bool) -> Iterator[Path | ExcludedFile]:
        yield from sorted(folder.iterdir())

    def inspect(self, path: Path) -> ImageFile:
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(5), "test worker was not released"
        if self.failure is not None:
            raise self.failure
        if path.suffix != ".jpg":
            raise FileInspectionError(ExclusionReason.UNSUPPORTED, "test unsupported file")
        content = path.read_bytes()
        return ImageFile(
            path, "JPEG", FileKind.STANDARD, len(content), hashlib.sha256(content).hexdigest()
        )


@dataclass
class Harness:
    client: TestClient
    jobs: ImportJobs
    folder: Path
    source: Source

    def start(self) -> dict[str, object]:
        response = self.client.post(
            "/api/v1/photos/imports", json={"source_folder": str(self.folder)}, headers=HEADERS
        )
        assert response.status_code == 202
        return response.json()

    def finish(self, job_id: object) -> dict[str, object]:
        for _ in range(500):
            response = self.client.get(f"/api/v1/photos/imports/{job_id}", headers=HEADERS)
            assert response.status_code == 200
            job = response.json()
            if job["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                return job
            time.sleep(0.01)
        pytest.fail("background photo import did not finish")


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    folder = tmp_path / "photos"
    folder.mkdir()
    with Image.new("RGB", (64, 32), "red") as image:
        image.save(folder / "photo.jpg")
    (folder / "notes.txt").write_text("notes", encoding="utf-8")
    db = Database.at(tmp_path / "data" / "shotkeepr.db")
    upgrade_to_head(db.url)
    source = Source()
    sessions, shots = SqlSessionRepository(db), SqlShotRepository(db)
    previews = PillowRawPreviewStore(tmp_path / "cache")
    jobs = ImportJobs(
        lambda: PhotoImportService(source, previews, sessions, SqlCatalogWriter(db)),
        sessions,
        shots,
        previews,
    )
    service = ConfigurationService(SqlSettingsRepository(db), EnvSecretStore({}))
    try:
        with TestClient(create_app(service, "test-photo-token", import_jobs=jobs)) as client:
            yield Harness(client, jobs, folder, source)
    finally:
        if source.gate is not None:
            source.gate.set()
        jobs.shutdown()
        db.dispose()


def test_background_import_progress_catalog_and_authenticated_thumbnail(harness: Harness) -> None:
    events = harness.jobs.events.subscribe()
    started = harness.start()
    finished = harness.finish(started["job_id"])
    assert finished["status"] == "SUCCEEDED"
    assert finished["imported_files"] == finished["shots"] == 1
    assert finished["excluded_files"] == 1
    assert finished["processed"] == 2
    assert events.get(timeout=2).payload["operation"] == "photo-import"
    harness.jobs.events.unsubscribe(events)
    session_id = finished["session_id"]
    session = harness.client.get(f"/api/v1/photos/sessions/{session_id}", headers=HEADERS).json()
    assert session["status"] == "IMPORTED"
    assert session["excluded"][0]["reason"] == "UNSUPPORTED"
    page = harness.client.get(f"/api/v1/photos/sessions/{session_id}/shots", headers=HEADERS).json()
    assert page["total"] == 1
    assert len(page["items"]) == 1
    shot_id = page["items"][0]["shot_id"]
    thumbnail = harness.client.get(f"/api/v1/photos/shots/{shot_id}/thumbnail", headers=HEADERS)
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(thumbnail.content)) as preview:
        assert preview.size == (64, 32)
    assert harness.client.get(f"/api/v1/photos/shots/{shot_id}/thumbnail").status_code == 401
    listing = harness.client.get("/api/v1/photos/sessions", headers=HEADERS).json()
    assert listing[0]["session_id"] == session_id


def test_import_does_not_block_health_and_rejects_overlapping_jobs(harness: Harness) -> None:
    harness.source.gate = threading.Event()
    started = harness.start()
    try:
        assert harness.source.entered.wait(2)
        assert harness.client.get("/api/v1/health").status_code == 200
        busy = harness.client.post(
            "/api/v1/photos/imports", json={"source_folder": str(harness.folder)}, headers=HEADERS
        )
        assert busy.status_code == 409
        assert (
            harness.client.get(
                f"/api/v1/photos/imports/{started['job_id']}", headers=HEADERS
            ).json()["status"]
            == "RUNNING"
        )
    finally:
        harness.source.gate.set()
    assert harness.finish(started["job_id"])["status"] == "SUCCEEDED"


def test_cancel_is_cooperative_and_does_not_publish_partial_shots(harness: Harness) -> None:
    harness.source.gate = threading.Event()
    started = harness.start()
    try:
        assert harness.source.entered.wait(2)
        response = harness.client.post(
            f"/api/v1/photos/imports/{started['job_id']}/cancel", headers=HEADERS
        )
        assert response.status_code == 200
        assert response.json()["cancel_requested"] is True
    finally:
        harness.source.gate.set()
    cancelled = harness.finish(started["job_id"])
    assert cancelled["status"] == "CANCELLED"
    session = harness.jobs.sessions.get(uuid.UUID(str(cancelled["session_id"])))
    assert session is not None and session.status is SessionStatus.CANCELLED
    assert harness.jobs.shots.count_by_session(session.session_id) == 0
    assert harness.start()["job_id"] != started["job_id"]


def test_unexpected_worker_failure_is_visible_and_recorded(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    harness.source.failure = RuntimeError("unexpected decoder failure")
    failed = harness.finish(harness.start()["job_id"])
    assert failed["status"] == "FAILED"
    assert failed["error"]
    # La callback aggiorna anche il catalogo, non solo lo stato in memoria.
    for _ in range(100):
        session = harness.jobs.sessions.get(uuid.UUID(str(failed["session_id"])))
        if session is not None and session.status is SessionStatus.FAILED:
            break
        time.sleep(0.01)
    assert session is not None and session.status is SessionStatus.FAILED
    assert "unexpected decoder failure" in caplog.text


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1"])
def test_shot_pages_are_bounded(harness: Harness, query: str) -> None:
    finished = harness.finish(harness.start()["job_id"])
    assert (
        harness.client.get(
            f"/api/v1/photos/sessions/{finished['session_id']}/shots?{query}", headers=HEADERS
        ).status_code
        == 422
    )


def test_unknown_job_session_shot_and_cancel_are_not_successes(harness: Harness) -> None:
    identifier = uuid.uuid4()
    for path in (
        f"imports/{identifier}",
        f"sessions/{identifier}",
        f"shots/{identifier}/thumbnail",
    ):
        assert harness.client.get(f"/api/v1/photos/{path}", headers=HEADERS).status_code == 404
    assert (
        harness.client.post(
            f"/api/v1/photos/imports/{identifier}/cancel", headers=HEADERS
        ).status_code
        == 404
    )


def test_import_requires_authentication_and_absolute_core_path(harness: Harness) -> None:
    assert (
        harness.client.post(
            "/api/v1/photos/imports", json={"source_folder": str(harness.folder)}
        ).status_code
        == 401
    )
    assert (
        harness.client.post(
            "/api/v1/photos/imports", json={"source_folder": "relative"}, headers=HEADERS
        ).status_code
        == 400
    )
    assert (
        harness.client.post(
            "/api/v1/photos/imports", json={"source_folder": ""}, headers=HEADERS
        ).status_code
        == 422
    )


def test_shutdown_cancels_active_import_and_rejects_new_work(harness: Harness) -> None:
    harness.source.gate = threading.Event()
    started = harness.start()
    assert harness.source.entered.wait(2)
    stopper = threading.Thread(target=harness.jobs.shutdown)
    stopper.start()
    harness.source.gate.set()
    stopper.join(timeout=5)
    assert not stopper.is_alive()
    assert harness.jobs.get(uuid.UUID(str(started["job_id"]))).status is ImportJobStatus.CANCELLED
    assert (
        harness.client.post(
            "/api/v1/photos/imports", json={"source_folder": str(harness.folder)}, headers=HEADERS
        ).status_code
        == 409
    )


def test_missing_metadata_service_is_a_visible_503(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable() -> PhotoImportService:
        raise ExifToolUnavailableError("ExifTool non disponibile")

    monkeypatch.setattr(harness.jobs, "_factory", unavailable)
    response = harness.client.post(
        "/api/v1/photos/imports", json={"source_folder": str(harness.folder)}, headers=HEADERS
    )
    assert response.status_code == 503
    assert "ExifTool" in response.json()["detail"]
    assert harness.jobs.sessions.list() == []


def test_completed_import_cannot_be_undone_by_late_cancellation(harness: Harness) -> None:
    completed = harness.finish(harness.start()["job_id"])
    response = harness.client.post(
        f"/api/v1/photos/imports/{completed['job_id']}/cancel", headers=HEADERS
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCEEDED"
    assert response.json()["shots"] == 1


def test_job_history_is_bounded_and_completed_catalog_survives_eviction(harness: Harness) -> None:
    first = harness.finish(harness.start()["job_id"])
    for _ in range(MAX_RETAINED_JOBS):
        harness.finish(harness.start()["job_id"])
    assert (
        harness.client.get(f"/api/v1/photos/imports/{first['job_id']}", headers=HEADERS).status_code
        == 404
    )
    assert (
        harness.client.get(
            f"/api/v1/photos/sessions/{first['session_id']}", headers=HEADERS
        ).json()["status"]
        == "IMPORTED"
    )
