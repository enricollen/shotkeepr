import shutil
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from shotkeepr.desktop import photos as bridge
from shotkeepr.desktop.api_client.models import (
    ApiError,
    SessionOut,
    SessionStatus,
    ShotOut,
    ShotPageOut,
)
from shotkeepr.desktop.connection import CoreConnection
from shotkeepr.desktop.photos import PhotoController, PhotoPage, PhotoSessions, Thumbnail
from shotkeepr.desktop.runtime import CoreRuntime
from shotkeepr.desktop.window import MainWindow

from .test_photos import _pictures


def _session(*, day: int = 0, status: SessionStatus = SessionStatus.IMPORTED) -> SessionOut:
    return SessionOut(
        session_id=uuid.uuid4(),
        source_folder="/photos/not-on-the-desktop-host",
        include_subfolders=False,
        status=status,
        processed=1,
        shots=1,
        started_at=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(days=day),
        excluded=[],
    )


def _page(session: SessionOut, *, offset: int = 0, total: int = 2) -> PhotoPage:
    shot = ShotOut(shot_id=uuid.uuid4(), capture_time=None, is_raw_pair=False, files=[])
    page = ShotPageOut(items=[shot], offset=offset, limit=bridge.PAGE_SIZE, total=total)
    return PhotoPage(session, page, (Thumbnail(shot, None),))


@contextmanager
def _running_window(qt_app: QApplication, wait_until: Callable, data: Path) -> Iterator[MainWindow]:
    runtime = CoreRuntime(data_dir=data)
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    runtime.ready.connect(connection.connect_to)
    window.show()
    try:
        runtime.start()
        wait_until(lambda: window._connected and window.photos._worker is None)
        yield window
    finally:
        window.close()
        connection.shutdown()
        runtime.stop()


def test_saved_sessions_are_sorted_without_blocking_qt_and_requests_are_serialized(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    older, newer = _session(), _session(day=1)

    def slow_list(**kwargs: object) -> SimpleNamespace:
        time.sleep(0.15)
        return SimpleNamespace(parsed=[older, newer], status_code=200)

    monkeypatch.setattr(bridge.list_photo_sessions, "sync_detailed", slow_list)
    controller = PhotoController()
    received: list[PhotoSessions] = []
    errors: list[str] = []
    ticks: list[bool] = []
    controller.sessions_received.connect(received.append)
    controller.failed.connect(errors.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.refresh_sessions()
        controller.open_session(newer.session_id)
        controller.start_import("/photos", True)
        QTimer.singleShot(20, lambda: ticks.append(not received))
        wait_until(lambda: bool(received) and controller._worker is None)
        assert ticks == [True]
        assert received[0].items == (newer, older)
        assert errors == ["Attendere la fine dell'operazione corrente."] * 2
        assert controller.session_id is None
        assert not controller._active
    finally:
        controller.shutdown()


@pytest.mark.parametrize("payload", [[], None, [object()], ApiError(detail="Catalogo assente")])
def test_empty_invalid_and_failed_session_lists_are_not_confused(
    qt_app: QApplication,
    wait_until: Callable,
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    monkeypatch.setattr(
        bridge.list_photo_sessions,
        "sync_detailed",
        lambda **kwargs: SimpleNamespace(parsed=payload, status_code=200),
    )
    controller = PhotoController()
    received: list[PhotoSessions] = []
    errors: list[str] = []
    controller.sessions_received.connect(received.append)
    controller.failed.connect(errors.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.refresh_sessions()
        wait_until(lambda: bool(received or errors) and controller._worker is None)
        if payload == []:
            assert received == [PhotoSessions(())]
            assert not errors
        else:
            assert not received
            assert errors
    finally:
        controller.shutdown()


def test_session_list_refresh_is_deferred_until_import_is_idle(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        bridge.list_photo_sessions,
        "sync_detailed",
        lambda **kwargs: SimpleNamespace(parsed=[], status_code=200),
    )
    controller = PhotoController()
    received: list[PhotoSessions] = []
    controller.sessions_received.connect(received.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller._active = True
        controller.refresh_sessions()
        assert controller._sessions_pending
        assert controller._worker is None
        controller._active = False
        controller._finished()
        wait_until(lambda: bool(received) and controller._worker is None)
        assert received == [PhotoSessions(())]
        assert not controller._sessions_pending
    finally:
        controller.shutdown()


@pytest.mark.parametrize("status", [SessionStatus.IMPORTING, SessionStatus.ANALYZING])
def test_session_still_processing_is_not_opened(
    qt_app: QApplication,
    wait_until: Callable,
    monkeypatch: pytest.MonkeyPatch,
    status: SessionStatus,
) -> None:
    session = _session(status=status)
    monkeypatch.setattr(
        bridge.get_photo_session,
        "sync_detailed",
        lambda *args, **kwargs: SimpleNamespace(parsed=session, status_code=200),
    )
    controller = PhotoController()
    pages: list[PhotoPage] = []
    errors: list[str] = []
    controller.page_received.connect(pages.append)
    controller.failed.connect(errors.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.open_session(session.session_id)
        wait_until(lambda: bool(errors) and controller._worker is None)
        assert not pages
        assert controller.session_id is None
        assert "ancora in elaborazione" in errors[0]
    finally:
        controller.shutdown()


def test_switching_sessions_replaces_the_grid_and_uses_core_paths(qt_app: QApplication) -> None:
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    first, second = _session(), _session(day=1)
    window._connected = True
    try:
        window._sessions_received(PhotoSessions((second, first)))
        assert window.session_combo.count() == 2
        assert window.open_session_button.isEnabled()
        window.photos._success(_page(first))
        window.photos._success(_page(first, offset=1))
        assert window.photo_grid.count() == 2
        window._sessions_received(
            PhotoSessions(
                (SessionOut.from_dict(second.to_dict()), SessionOut.from_dict(first.to_dict()))
            )
        )
        assert window.session_combo.currentData() == str(first.session_id)
        assert window.photo_grid.count() == 2
        window.photos._success(_page(second, total=1))
        assert window.photo_grid.count() == 1
        assert window.photos.session_id == second.session_id
        assert window.photos._offset == 1
        assert window.session_combo.currentData() == str(second.session_id)
        assert window.source_edit.text() == second.source_folder
        assert window.source_label.text() == second.source_folder
        assert not window.recursive_check.isChecked()
        assert not window.load_more_button.isEnabled()
        window._set_import_active(True)
        assert not window.open_session_button.isEnabled()
        assert not window.refresh_sessions_button.isEnabled()
        assert not window.session_combo.isEnabled()
        window._set_import_active(False)
        assert window.open_session_button.isEnabled()
        window._sessions_received(PhotoSessions(()))
        assert not window.open_session_button.isEnabled()
        assert window.refresh_sessions_button.isEnabled()
    finally:
        window.close()
        connection.shutdown()


@pytest.mark.parametrize("operation", ["open", "refresh"])
def test_catalog_errors_preserve_displayed_session_and_allow_retry(
    qt_app: QApplication,
    wait_until: Callable,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    session = _session()
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "test-token")
    window._sessions_received(PhotoSessions((session,)))
    window.photos._success(_page(session))
    original_shot = window.photo_grid.item(0).data(256).shot_id
    try:
        if operation == "open":
            monkeypatch.setattr(
                bridge.get_photo_session,
                "sync_detailed",
                lambda *args, **kwargs: SimpleNamespace(
                    parsed=ApiError(detail="Sessione non presente"), status_code=404
                ),
            )
            window.photos.open_session(uuid.uuid4())
        else:

            def offline(**kwargs: object) -> None:
                raise httpx.ConnectError("offline")

            monkeypatch.setattr(bridge.list_photo_sessions, "sync_detailed", offline)
            window.refresh_sessions_button.click()
        wait_until(lambda: window.photos._worker is None)
        assert window.photo_grid.count() == 1
        assert window.photo_grid.item(0).data(256).shot_id == original_shot
        assert window.photos.session_id == session.session_id
        assert window.photos._offset == 1
        assert window.session_combo.count() == 1
        assert window.open_session_button.isEnabled()
        assert window.refresh_sessions_button.isEnabled()
        assert window.statusBar().currentMessage()
        assert window.load_more_button.isEnabled()
    finally:
        window.close()
        connection.shutdown()


def test_reopen_and_page_saved_sessions_after_core_restart_without_original_folder(
    qt_app: QApplication, wait_until: Callable, tmp_path: Path
) -> None:
    if shutil.which("exiftool") is None:
        pytest.skip("ExifTool richiesto per importare tramite il nucleo reale")
    folder, other_folder = tmp_path / "photos", tmp_path / "other-photos"
    _pictures(folder, bridge.PAGE_SIZE + 2)
    _pictures(other_folder, 1)
    (folder / "notes.txt").write_text("not a photograph", encoding="utf-8")
    originals = {path.name: path.read_bytes() for path in folder.iterdir()}
    data = tmp_path / "data"
    with _running_window(qt_app, wait_until, data) as first:
        first.select_folder(str(folder))
        first.import_button.click()
        wait_until(lambda: first.photo_grid.count() == bridge.PAGE_SIZE and not first._photo_busy)
        session_id = first.photos.session_id
        assert session_id is not None
        assert first.session_combo.count() == 1
        first.load_more_button.click()
        wait_until(
            lambda: first.photo_grid.count() == bridge.PAGE_SIZE + 2 and not first._photo_busy
        )
        identifiers = {
            first.photo_grid.item(index).data(256).shot_id
            for index in range(first.photo_grid.count())
        }
        first.select_folder(str(other_folder))
        first.import_button.click()
        wait_until(lambda: first.photo_grid.count() == 1 and not first._photo_busy)
        assert first.session_combo.count() == 2
        other_id = first.photos.session_id
    moved = tmp_path / "offline-originals"
    folder.rename(moved)
    with _running_window(qt_app, wait_until, data) as reopened:
        assert reopened.photo_grid.count() == 0
        assert reopened.session_combo.count() == 2
        reopened.session_combo.setCurrentIndex(reopened.session_combo.findData(str(session_id)))
        reopened.open_session_button.click()
        wait_until(
            lambda: reopened.photo_grid.count() == bridge.PAGE_SIZE and not reopened._photo_busy
        )
        assert reopened.photos.session_id == session_id
        assert reopened.source_edit.text() == str(folder)
        assert reopened.exclusions.count() == 1
        assert not reopened.photo_grid.item(0).icon().isNull()
        reopened.load_more_button.click()
        wait_until(
            lambda: reopened.photo_grid.count() == bridge.PAGE_SIZE + 2 and not reopened._photo_busy
        )
        assert {
            reopened.photo_grid.item(index).data(256).shot_id
            for index in range(reopened.photo_grid.count())
        } == identifiers
        assert not reopened.load_more_button.isEnabled()
        reopened.session_combo.setCurrentIndex(reopened.session_combo.findData(str(other_id)))
        reopened.open_session_button.click()
        wait_until(lambda: reopened.photo_grid.count() == 1 and not reopened._photo_busy)
        assert reopened.photos.session_id == other_id
        assert reopened.exclusions.count() == 0
    assert {path.name: path.read_bytes() for path in moved.iterdir()} == originals
