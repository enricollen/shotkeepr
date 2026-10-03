import shutil
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from shotkeepr.desktop import photos as bridge
from shotkeepr.desktop.api_client.models import (
    ApiError,
    ExposureOut,
    SessionOut,
    SessionStatus,
    SharpnessOut,
    ShotOut,
    ShotPageOut,
)
from shotkeepr.desktop.connection import CoreConnection
from shotkeepr.desktop.photos import PhotoController, PhotoPage, PreviewBatch
from shotkeepr.desktop.window import MainWindow

from .test_exposure import _measurement as _exposure
from .test_exposure import _shot_with_metadata
from .test_sessions import _page, _running_window, _session
from .test_sharpness import _measurement as _sharpness


def _catalog(
    monkeypatch: pytest.MonkeyPatch, count: int
) -> tuple[SessionOut, list[ShotOut], list[tuple[int, int]]]:
    session = _session()
    session.shots = count
    shots = [_shot_with_metadata(_page(session)) for _ in range(count)]
    requests: list[tuple[int, int]] = []

    def listing(
        *args: object, offset: int = 0, limit: int = bridge.PAGE_SIZE, **kwargs: object
    ) -> SimpleNamespace:
        assert "group_id" not in kwargs and "ungrouped" not in kwargs
        requests.append((offset, limit))
        page = ShotPageOut(
            items=shots[offset : offset + limit], total=count, offset=offset, limit=limit
        )
        return SimpleNamespace(parsed=page, status_code=200)

    monkeypatch.setattr(
        bridge.get_photo_session,
        "sync_detailed",
        lambda *args, **kwargs: SimpleNamespace(parsed=session, status_code=200),
    )
    monkeypatch.setattr(bridge.list_photo_shots, "sync_detailed", listing)
    monkeypatch.setattr(
        bridge.measure_photo_exposure,
        "sync_detailed",
        lambda shot_id, **kwargs: SimpleNamespace(parsed=_exposure(shot_id), status_code=200),
    )
    monkeypatch.setattr(
        bridge.measure_photo_sharpness,
        "sync_detailed",
        lambda shot_id, **kwargs: SimpleNamespace(parsed=_sharpness(shot_id), status_code=200),
    )
    return session, shots, requests


def test_measures_all_session_pages_without_changing_the_current_filtered_view(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    count = bridge.PAGE_SIZE + 2
    session, shots, requests = _catalog(monkeypatch, count)
    controller = PhotoController()
    group = uuid.uuid4()
    page = _page(session, offset=7)
    controller._success(PhotoPage(page.session, page.page, page.thumbnails, group))
    received: list[PreviewBatch] = []
    measured: list[ExposureOut | SharpnessOut] = []
    progress: list[tuple[int, int]] = []
    errors: list[str] = []
    controller.measurements_finished.connect(received.append)
    controller.exposure_received.connect(measured.append)
    controller.sharpness_received.connect(measured.append)
    controller.measurement_progress.connect(lambda done, total: progress.append((done, total)))
    controller.failed.connect(errors.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.measure_session()
        controller.measure_session()
        wait_until(lambda: bool(received) and controller._worker is None)
        assert received == [PreviewBatch(session.session_id, count, count, False)]
        assert requests == [(0, bridge.PAGE_SIZE), (bridge.PAGE_SIZE, bridge.PAGE_SIZE)]
        assert len(measured) == count * 2
        assert [item.shot_id for item in measured[::2]] == [shot.shot_id for shot in shots]
        assert all(isinstance(item, SharpnessOut) for item in measured[1::2])
        assert progress == [(index, count) for index in range(count + 1)]
        assert errors == ["Attendere la fine dell'operazione corrente."]
        assert controller.session_id == session.session_id
        assert controller._offset == 8
        assert controller.view_group_id == group
        assert not controller._active and controller._job_id is None
    finally:
        controller.shutdown()


def test_cancellation_between_requests_preserves_partial_results_and_qt_responsiveness(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, shots, requests = _catalog(monkeypatch, 2)
    entered, release = threading.Event(), threading.Event()

    def blocked(shot_id: uuid.UUID, **kwargs: object) -> SimpleNamespace:
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(parsed=_exposure(shot_id), status_code=200)

    def unexpected_sharpness(*args: object, **kwargs: object) -> None:
        pytest.fail("cancellation must stop before the next measurement")

    monkeypatch.setattr(bridge.measure_photo_exposure, "sync_detailed", blocked)
    monkeypatch.setattr(bridge.measure_photo_sharpness, "sync_detailed", unexpected_sharpness)
    controller = PhotoController()
    controller._success(_page(session))
    received: list[PreviewBatch] = []
    measured: list[ExposureOut] = []
    ticks: list[bool] = []
    errors: list[str] = []
    controller.measurements_finished.connect(received.append)
    controller.exposure_received.connect(measured.append)
    controller.failed.connect(errors.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.measure_session()
        QTimer.singleShot(0, lambda: ticks.append(controller.measuring_session))
        wait_until(entered.is_set)
        assert ticks == [True]
        controller.cancel_measurements()
        assert controller.measurement_cancel_requested
        release.set()
        wait_until(lambda: controller._worker is None)
        assert received == [PreviewBatch(session.session_id, 0, 2, True)]
        assert [item.shot_id for item in measured] == [shots[0].shot_id]
        assert requests == [(0, bridge.PAGE_SIZE)]
        assert not errors
        assert not controller.measuring_session
    finally:
        release.set()
        controller.shutdown()


@pytest.mark.parametrize("failure", ["api", "network", "invalid", "wrong-shot"])
def test_failure_keeps_completed_measurements_and_retry_is_available(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    session, shots, _requests = _catalog(monkeypatch, 2)

    def failed(shot_id: uuid.UUID, **kwargs: object) -> SimpleNamespace:
        if shot_id == shots[0].shot_id:
            return SimpleNamespace(parsed=_sharpness(shot_id), status_code=200)
        if failure == "network":
            raise httpx.ConnectError("private-token")
        parsed = (
            ApiError(detail="anteprima corrotta")
            if failure == "api"
            else _sharpness(uuid.uuid4())
            if failure == "wrong-shot"
            else None
        )
        return SimpleNamespace(parsed=parsed, status_code=409)

    monkeypatch.setattr(bridge.measure_photo_sharpness, "sync_detailed", failed)
    controller = PhotoController()
    controller._success(_page(session))
    errors: list[str] = []
    received: list[PreviewBatch] = []
    measured: list[SharpnessOut] = []
    controller.failed.connect(errors.append)
    controller.measurements_finished.connect(received.append)
    controller.sharpness_received.connect(measured.append)
    try:
        controller.configure("http://127.0.0.1:12345", "private-token")
        controller.measure_session()
        wait_until(lambda: controller._worker is None)
        assert not received
        assert len(errors) == 1
        assert "1/2 scatti completati" in errors[0]
        assert "gia' salvate restano disponibili" in errors[0]
        assert "private-token" not in errors[0]
        assert [item.shot_id for item in measured] == [shots[0].shot_id]
        monkeypatch.setattr(
            bridge.measure_photo_sharpness,
            "sync_detailed",
            lambda shot_id, **kwargs: SimpleNamespace(parsed=_sharpness(shot_id), status_code=200),
        )
        controller.measure_session()
        wait_until(lambda: bool(received) and controller._worker is None)
        assert received == [PreviewBatch(session.session_id, 2, 2, False)]
        assert controller._offset == 1
    finally:
        controller.shutdown()


@pytest.mark.parametrize("invalid", ["empty", "offset", "total", "duplicates", "oversized"])
def test_invalid_pagination_is_not_reported_as_success(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    session, shots, _requests = _catalog(monkeypatch, 2)
    page = ShotPageOut(items=shots, offset=0, total=2, limit=bridge.PAGE_SIZE)
    if invalid == "empty":
        page.items = []
    elif invalid == "offset":
        page.offset = 1
    elif invalid == "total":
        page.total = 3
    elif invalid == "duplicates":
        page.items = [shots[0], shots[0]]
    else:
        page.items = [*shots, _page(session).page.items[0]]
    monkeypatch.setattr(
        bridge.list_photo_shots,
        "sync_detailed",
        lambda *args, **kwargs: SimpleNamespace(parsed=page, status_code=200),
    )
    controller = PhotoController()
    controller._success(_page(session))
    errors: list[str] = []
    received: list[PreviewBatch] = []
    measured: list[ExposureOut] = []
    controller.failed.connect(errors.append)
    controller.measurements_finished.connect(received.append)
    controller.exposure_received.connect(measured.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.measure_session()
        wait_until(lambda: controller._worker is None)
        assert len(errors) == 1
        assert not received and not measured
        assert "0/2 scatti completati" in errors[0]
    finally:
        controller.shutdown()


@pytest.mark.parametrize(
    "status", [SessionStatus.IMPORTED, SessionStatus.ANALYZED, SessionStatus.IMPORTING]
)
def test_empty_and_unfinished_sessions_are_distinguished(
    qt_app: QApplication,
    wait_until: Callable,
    monkeypatch: pytest.MonkeyPatch,
    status: SessionStatus,
) -> None:
    session, _shots, requests = _catalog(monkeypatch, 0)
    session.status = status
    controller = PhotoController()
    controller._success(_page(session))
    errors: list[str] = []
    received: list[PreviewBatch] = []
    controller.failed.connect(errors.append)
    controller.measurements_finished.connect(received.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.measure_session()
        wait_until(lambda: controller._worker is None)
        assert not requests
        if status is SessionStatus.IMPORTING:
            assert len(errors) == 1 and not received
        else:
            assert not errors
            assert received == [PreviewBatch(session.session_id, 0, 0, False)]
    finally:
        controller.shutdown()


def test_measurements_require_a_connected_open_idle_session(qt_app: QApplication) -> None:
    controller = PhotoController()
    errors: list[str] = []
    controller.failed.connect(errors.append)
    try:
        controller.measure_session()
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.measure_session()
        controller._session_id = uuid.uuid4()
        controller._active = True
        controller.measure_session()
        controller.cancel_measurements()
        assert len(errors) == 4
        assert controller._worker is None
    finally:
        controller.shutdown()


def test_gui_preserves_selected_shot_and_filters_while_measuring_the_entire_session(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, shots, _requests = _catalog(monkeypatch, 2)
    page = _page(session)
    page.page.items = [shots[0]]
    page = PhotoPage(session, page.page, (bridge.Thumbnail(shots[0], None),), ungrouped=True)
    entered, release = threading.Event(), threading.Event()

    def blocked(shot_id: uuid.UUID, **kwargs: object) -> SimpleNamespace:
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(parsed=_exposure(shot_id), status_code=200)

    monkeypatch.setattr(bridge.measure_photo_exposure, "sync_detailed", blocked)
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "test-token")
    window.photos._success(page)
    try:
        window.measure_session_button.click()
        wait_until(entered.is_set)
        assert not window.measure_session_button.isEnabled()
        assert not window.open_session_button.isEnabled()
        assert window.cancel_measurements_button.isEnabled()
        assert window.photo_grid.isEnabled()
        release.set()
        wait_until(lambda: window.photos._worker is None)
        shown = window._selected_shot()
        assert shown.shot_id == shots[0].shot_id
        assert isinstance(shown.exposure, ExposureOut) and isinstance(shown.sharpness, SharpnessOut)
        assert window.photo_grid.count() == 1
        assert window.photos._offset == 1 and window.photos.view_ungrouped
        assert "2/2 scatti" in window.import_status.text()
        assert window.import_progress.value() == 2
        assert window.measure_session_button.isEnabled()
        assert not window.cancel_measurements_button.isEnabled()
    finally:
        release.set()
        window.close()
        connection.shutdown()


def test_gui_cancellation_retains_partial_measurements_and_restores_controls(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, shots, _requests = _catalog(monkeypatch, 2)
    entered, release = threading.Event(), threading.Event()

    def blocked(shot_id: uuid.UUID, **kwargs: object) -> SimpleNamespace:
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(parsed=_exposure(shot_id), status_code=200)

    monkeypatch.setattr(bridge.measure_photo_exposure, "sync_detailed", blocked)
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "test-token")
    page = _page(session)
    window.photos._success(PhotoPage(session, page.page, (bridge.Thumbnail(shots[0], None),)))
    try:
        window.measure_session_button.click()
        wait_until(entered.is_set)
        window.cancel_measurements_button.click()
        assert not window.cancel_measurements_button.isEnabled()
        assert "Arresto" in window.import_status.text()
        release.set()
        wait_until(lambda: window.photos._worker is None)
        shown = window.photo_grid.item(0).data(256)
        assert isinstance(shown.exposure, ExposureOut)
        assert not isinstance(shown.sharpness, SharpnessOut)
        assert "Misure annullate: 0/2" in window.import_status.text()
        assert window.import_progress.value() == 0
        assert window.measure_session_button.isEnabled()
        assert not window.cancel_measurements_button.isEnabled()
    finally:
        release.set()
        window.close()
        connection.shutdown()


def test_catalog_error_before_progress_stops_the_indeterminate_bar(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, _shots, _requests = _catalog(monkeypatch, 2)
    monkeypatch.setattr(
        bridge.get_photo_session,
        "sync_detailed",
        lambda *args, **kwargs: SimpleNamespace(
            parsed=ApiError(detail="sessione non presente"), status_code=404
        ),
    )
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "test-token")
    window.photos._success(_page(session))
    try:
        window.measure_session_button.click()
        wait_until(lambda: window.photos._worker is None)
        assert "sessione non presente" in window.import_status.text()
        assert window.import_progress.maximum() == 1
        assert window.measure_session_button.isEnabled()
        assert window.photo_grid.count() == 1
    finally:
        window.close()
        connection.shutdown()


def test_shutdown_stops_before_scheduling_more_measurements(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, _shots, _requests = _catalog(monkeypatch, 2)
    entered = threading.Event()
    calls: list[uuid.UUID] = []
    controller = PhotoController()

    def in_flight(shot_id: uuid.UUID, **kwargs: object) -> SimpleNamespace:
        entered.set()
        calls.append(shot_id)
        worker = controller._worker
        assert worker is not None
        for _ in range(1000):
            if worker.isInterruptionRequested():
                break
            threading.Event().wait(0.001)
        assert worker.isInterruptionRequested()
        return SimpleNamespace(parsed=_exposure(shot_id), status_code=200)

    monkeypatch.setattr(bridge.measure_photo_exposure, "sync_detailed", in_flight)
    controller._success(_page(session))
    received: list[PreviewBatch] = []
    measured: list[ExposureOut] = []
    controller.measurements_finished.connect(received.append)
    controller.exposure_received.connect(measured.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.measure_session()
        wait_until(entered.is_set)
        controller.shutdown()
        qt_app.processEvents()
        assert controller._worker is None
        assert len(calls) == 1
        assert not received and not measured
    finally:
        controller.shutdown()


def test_real_session_measurements_are_cached_after_restart_without_originals(
    qt_app: QApplication, wait_until: Callable, tmp_path: Path
) -> None:
    if shutil.which("exiftool") is None:
        pytest.skip("ExifTool required for photographic import")
    folder = tmp_path / "photos"
    folder.mkdir()
    for name, color in (("first", "gray"), ("second", "white")):
        with Image.new("RGB", (64, 32), color) as image:
            image.save(folder / f"{name}.png")
    originals = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in folder.iterdir()
    }
    data = tmp_path / "catalog"
    errors: list[str] = []

    def wait_for_catalog(predicate: Callable[[], bool]) -> None:
        wait_until(lambda: bool(errors) or predicate())
        assert not errors, errors

    with _running_window(qt_app, wait_for_catalog, data) as first:
        first.photos.failed.connect(errors.append)
        first.select_folder(str(folder))
        first.import_button.click()
        wait_for_catalog(lambda: first.photo_grid.count() == 2 and not first._photo_busy)
        session_id = first.photos.session_id
        first.measure_session_button.click()
        wait_for_catalog(lambda: not first._photo_busy)
        saved = {
            str(first.photo_grid.item(index).data(256).shot_id): (
                first.photo_grid.item(index).data(256).exposure.to_dict(),
                first.photo_grid.item(index).data(256).sharpness.to_dict(),
            )
            for index in range(2)
        }
        assert "Misure completate: 2/2" in first.import_status.text()
    moved = tmp_path / "offline-originals"
    folder.rename(moved)
    with _running_window(qt_app, wait_for_catalog, data) as reopened:
        reopened.photos.failed.connect(errors.append)
        reopened.session_combo.setCurrentIndex(reopened.session_combo.findData(str(session_id)))
        reopened.open_session_button.click()
        wait_for_catalog(lambda: reopened.photo_grid.count() == 2 and not reopened._photo_busy)
        reopened.measure_session_button.click()
        wait_for_catalog(lambda: not reopened._photo_busy)
        for index in range(2):
            shot = reopened.photo_grid.item(index).data(256)
            assert (shot.exposure.to_dict(), shot.sharpness.to_dict()) == saved[str(shot.shot_id)]
            assert shot.review.status.value == "REVIEW"
        assert "Misure completate: 2/2" in reopened.import_status.text()
    assert not errors, errors
    assert {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in moved.iterdir()
    } == originals
