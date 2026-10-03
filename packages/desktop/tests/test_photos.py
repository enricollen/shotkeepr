import shutil
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from shotkeepr.desktop import photos as bridge
from shotkeepr.desktop.api_client import AuthenticatedClient
from shotkeepr.desktop.api_client.api.photos import get_photo_session
from shotkeepr.desktop.api_client.errors import UnexpectedStatus
from shotkeepr.desktop.api_client.models import (
    ImportJobOut,
    ImportJobStatus,
    SessionOut,
    SessionStatus,
)
from shotkeepr.desktop.connection import CoreConnection
from shotkeepr.desktop.photos import PhotoController
from shotkeepr.desktop.runtime import CoreRuntime
from shotkeepr.desktop.window import MainWindow


@pytest.fixture
def live_window(qt_app: QApplication, wait_until: Callable, tmp_path: Path) -> Iterator[MainWindow]:
    if shutil.which("exiftool") is None:
        pytest.skip("ExifTool richiesto per importare tramite il nucleo reale")
    runtime = CoreRuntime(data_dir=tmp_path / "data")
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    runtime.ready.connect(connection.connect_to)
    window.show()
    try:
        runtime.start()
        wait_until(lambda: window._connected and window.photos._worker is None)
        yield window
    finally:
        window.photos.shutdown()
        connection.shutdown()
        runtime.stop()
        window.close()


def _pictures(folder: Path, count: int) -> None:
    folder.mkdir()
    for index in range(count):
        with Image.new("RGB", (64, 32), (index % 256, index // 256, 50)) as image:
            image.save(folder / f"photo-{index:03}.png")


def test_real_desktop_import_displays_http_thumbnails_and_exclusions(
    live_window: MainWindow,
    wait_until: Callable,
    tmp_path: Path,
) -> None:
    folder = tmp_path / "photos"
    _pictures(folder, 2)
    (folder / "notes.txt").write_text("not a photograph", encoding="utf-8")
    originals = {path: path.read_bytes() for path in folder.iterdir()}
    live_window.select_folder(str(folder))
    assert live_window.import_button.isEnabled()
    live_window.import_button.click()
    wait_until(lambda: live_window.photo_grid.count() == 2 and live_window.photos._worker is None)
    assert live_window.photo_stack.currentWidget() is live_window.photo_grid
    assert live_window.exclusions.count() == 1
    assert "UNSUPPORTED" in live_window.exclusions.item(0).text()
    assert not live_window.photo_grid.item(0).icon().isNull()
    assert "non ancora valutata" in live_window.details_label.text()
    assert live_window.import_progress.value() == 1
    assert not live_window.cancel_button.isEnabled()
    assert {path: path.read_bytes() for path in folder.iterdir()} == originals


def test_desktop_loads_catalog_in_bounded_pages(
    live_window: MainWindow, wait_until: Callable, tmp_path: Path
) -> None:
    folder = tmp_path / "photos"
    _pictures(folder, bridge.PAGE_SIZE + 2)
    live_window.select_folder(str(folder))
    live_window.import_button.click()
    wait_until(
        lambda: (
            live_window.photo_grid.count() == bridge.PAGE_SIZE
            and live_window.photos._worker is None
        )
    )
    assert live_window.load_more_button.isEnabled()
    live_window.load_more_button.click()
    wait_until(
        lambda: (
            live_window.photo_grid.count() == bridge.PAGE_SIZE + 2
            and live_window.photos._worker is None
        )
    )
    assert not live_window.load_more_button.isEnabled()
    identifiers = {
        live_window.photo_grid.item(index).data(256).shot_id
        for index in range(live_window.photo_grid.count())
    }
    assert len(identifiers) == bridge.PAGE_SIZE + 2


def test_live_desktop_cancellation_never_displays_partial_catalog(
    live_window: MainWindow, wait_until: Callable, tmp_path: Path
) -> None:
    folder = tmp_path / "photos"
    _pictures(folder, 100)
    jobs: list[ImportJobOut] = []
    live_window.photos.job_updated.connect(jobs.append)
    live_window.select_folder(str(folder))
    live_window.import_button.click()
    wait_until(lambda: live_window.photos._job_id is not None)
    live_window.cancel_button.click()
    wait_until(
        lambda: (
            bool(jobs)
            and jobs[-1].status is ImportJobStatus.CANCELLED
            and live_window.photos._worker is None
        )
    )
    assert live_window.photo_grid.count() == 0
    assert "annullata" in live_window.import_status.text()
    assert live_window.import_button.isEnabled()


def _failed_job() -> ImportJobOut:
    return ImportJobOut.from_dict(
        {
            "job_id": str(uuid.uuid4()),
            "session_id": str(uuid.uuid4()),
            "source_folder": "/photos",
            "status": "FAILED",
            "processed": 0,
            "imported_files": 0,
            "excluded_files": 0,
            "shots": 0,
            "current_file": None,
            "error": "ExifTool non disponibile",
            "cancel_requested": False,
        }
    )


def test_import_http_does_not_block_qt_and_failure_is_visible(
    qt_app: QApplication,
    wait_until: Callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _failed_job()

    def slow_start(**kwargs: object) -> SimpleNamespace:
        time.sleep(0.15)
        return SimpleNamespace(parsed=job, status_code=202)

    monkeypatch.setattr(bridge.start_photo_import, "sync_detailed", slow_start)
    controller = PhotoController()
    completed: list[ImportJobOut] = []
    failures: list[str] = []
    ticks: list[bool] = []
    controller.job_updated.connect(completed.append)
    controller.failed.connect(failures.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.start_import("/photos", True)
        QTimer.singleShot(20, lambda: ticks.append(not completed))
        wait_until(lambda: bool(failures) and controller._worker is None)
        assert ticks == [True]
        assert "ExifTool" in failures[-1]
        assert not controller._active
    finally:
        controller.shutdown()


@pytest.mark.parametrize(
    "failure", [httpx.ConnectError("offline"), UnexpectedStatus(401, b"secret-token")]
)
def test_import_request_errors_do_not_expose_tokens(
    qt_app: QApplication,
    wait_until: Callable,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    def fail(**kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(bridge.start_photo_import, "sync_detailed", fail)
    controller = PhotoController()
    errors: list[str] = []
    controller.failed.connect(errors.append)
    try:
        controller.configure("http://127.0.0.1:12345", "secret-token")
        controller.start_import("/photos", True)
        wait_until(lambda: bool(errors) and controller._worker is None)
        assert "secret-token" not in errors[-1]
        assert not controller._active
    finally:
        controller.shutdown()


def test_closing_owned_core_finishes_cancellation_before_restart(
    qt_app: QApplication,
    wait_until: Callable,
    tmp_path: Path,
) -> None:
    if shutil.which("exiftool") is None:
        pytest.skip("ExifTool richiesto per importare tramite il nucleo reale")
    folder = tmp_path / "photos"
    _pictures(folder, 100)
    data = tmp_path / "data"
    runtime = CoreRuntime(data_dir=data)
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    runtime.ready.connect(connection.connect_to)
    window.closing.connect(connection.shutdown)
    window.closing.connect(runtime.stop)
    try:
        runtime.start()
        wait_until(lambda: window._connected and window.photos._worker is None)
        window.select_folder(str(folder))
        window.import_button.click()
        wait_until(lambda: window.photos._job_id is not None)
        session_id = window.photos._session_id
        assert session_id is not None
        window.close()
    finally:
        window.photos.shutdown()
        connection.shutdown()
        runtime.stop()
        window.close()

    restarted = CoreRuntime(data_dir=data)
    endpoint: list[tuple[str, str]] = []
    restarted.ready.connect(lambda url, token: endpoint.append((url, token)))
    loaded = CoreConnection()
    restarted.ready.connect(loaded.connect_to)
    connected: list[bool] = []
    loaded.status_changed.connect(lambda ok, message: connected.append(ok))
    try:
        restarted.start()
        wait_until(lambda: bool(connected) and connected[-1])
        with AuthenticatedClient(base_url=endpoint[0][0], token=endpoint[0][1]) as client:
            session = get_photo_session.sync(session_id, client=client)
            assert isinstance(session, SessionOut)
            assert session.status is SessionStatus.CANCELLED
            assert session.shots == 0
    finally:
        loaded.shutdown()
        restarted.stop()


def test_poll_failure_pauses_until_explicit_retry(
    qt_app: QApplication,
    wait_until: Callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _failed_job()
    job.status = ImportJobStatus.RUNNING
    job.error = None
    monkeypatch.setattr(
        bridge.start_photo_import,
        "sync_detailed",
        lambda **kwargs: SimpleNamespace(parsed=job, status_code=202),
    )
    calls: list[bool] = []

    def offline(*args: object, **kwargs: object) -> None:
        calls.append(True)
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(bridge.get_photo_import, "sync_detailed", offline)
    controller = PhotoController()
    errors: list[str] = []
    controller.failed.connect(errors.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test")
        controller.start_import("/photos", True)
        wait_until(lambda: bool(errors) and controller._worker is None)
        assert controller._active
        assert not controller._timer.isActive()
        assert calls == [True]
        finished = ImportJobOut.from_dict({**job.to_dict(), "status": "CANCELLED"})
        monkeypatch.setattr(
            bridge.get_photo_import,
            "sync_detailed",
            lambda *args, **kwargs: SimpleNamespace(parsed=finished, status_code=200),
        )
        controller.refresh_job()
        wait_until(lambda: not controller._active and controller._worker is None)
        assert len(errors) == 1
    finally:
        controller.shutdown()
