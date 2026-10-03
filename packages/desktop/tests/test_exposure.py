import shutil
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
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
    PhotoFileOut,
    ShotOut,
)
from shotkeepr.desktop.connection import CoreConnection
from shotkeepr.desktop.photos import PhotoController, PhotoPage, PhotoSessions
from shotkeepr.desktop.window import MainWindow

from .test_sessions import _page, _running_window, _session


def _measurement(shot_id: uuid.UUID) -> ExposureOut:
    return ExposureOut(
        shot_id=shot_id,
        source_fingerprint="a" * 64,
        preview_sha256="b" * 64,
        analyzer_version="preview-rgb-exposure-v1",
        measured_at=datetime.now(UTC),
        width=32,
        height=16,
        mean_luma=0.5,
        highlights_fraction=0.25,
        shadows_fraction=0.25,
        score=50,
    )


def _shot_with_metadata(page: PhotoPage) -> ShotOut:
    shot = page.page.items[0]
    shot.files = [
        PhotoFileOut.from_dict(
            {
                "file_id": str(uuid.uuid4()),
                "path": "/photos/photo.jpg",
                "format": "JPEG",
                "kind": "STANDARD",
                "size_bytes": 100,
                "metadata": {
                    "camera_model": "Test camera",
                    "camera_serial": None,
                    "lens": None,
                    "focal_mm": None,
                    "exposure_s": None,
                    "aperture": None,
                    "iso": 100,
                    "capture_time": None,
                },
            }
        )
    ]
    return shot


def test_measurement_does_not_block_qt_or_change_paging_state(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _measurement(uuid.uuid4())

    def slow_measure(*args: object, **kwargs: object) -> SimpleNamespace:
        time.sleep(0.15)
        return SimpleNamespace(parsed=result, status_code=200)

    monkeypatch.setattr(bridge.measure_photo_exposure, "sync_detailed", slow_measure)
    controller = PhotoController()
    received: list[ExposureOut] = []
    ticks: list[bool] = []
    errors: list[str] = []
    controller.exposure_received.connect(received.append)
    controller.failed.connect(errors.append)
    session_id = uuid.uuid4()
    controller._session_id, controller._offset = session_id, 40
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.measure_exposure(result.shot_id)
        controller.measure_exposure(result.shot_id)
        QTimer.singleShot(20, lambda: ticks.append(not received))
        wait_until(lambda: bool(received) and controller._worker is None)
        assert received == [result]
        assert ticks == [True]
        assert errors == ["Attendere la fine dell'operazione corrente."]
        assert controller.session_id == session_id
        assert controller._offset == 40
        assert controller._job_id is None
        assert not controller._active
    finally:
        controller.shutdown()


@pytest.mark.parametrize("failure", ["api", "network", "invalid"])
def test_exposure_errors_preserve_the_view_and_allow_retry(
    qt_app: QApplication,
    wait_until: Callable,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    def failed_measure(*args: object, **kwargs: object) -> SimpleNamespace:
        if failure == "network":
            raise httpx.ConnectError("token-must-not-be-shown")
        parsed = ApiError(detail="anteprima non accessibile") if failure == "api" else None
        return SimpleNamespace(parsed=parsed, status_code=409)

    monkeypatch.setattr(bridge.measure_photo_exposure, "sync_detailed", failed_measure)
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "token-must-not-be-shown")
    session = _session()
    page = _page(session)
    shot = _shot_with_metadata(page)
    window._sessions_received(PhotoSessions((session,)))
    window.photos._success(page)
    try:
        assert window.exposure_button.isEnabled()
        window.exposure_button.click()
        wait_until(lambda: window.photos._worker is None)
        assert window.photo_grid.count() == 1
        assert window.photos.session_id == session.session_id
        assert window.photos._offset == 1
        assert window.photo_grid.item(0).data(256).shot_id == shot.shot_id
        assert window.statusBar().currentMessage()
        assert "token-must-not-be-shown" not in window.statusBar().currentMessage()
        assert "non ancora misurata" in window.details_label.text()
        assert window.exposure_button.isEnabled()
    finally:
        window.close()
        connection.shutdown()


def test_changing_selection_during_measurement_does_not_show_another_shots_result(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session()
    first, second = _page(session), _page(session, offset=1)
    first_shot = _shot_with_metadata(first)
    second_shot = _shot_with_metadata(second)
    result = _measurement(first_shot.shot_id)

    def slow_measure(*args: object, **kwargs: object) -> SimpleNamespace:
        time.sleep(0.15)
        return SimpleNamespace(parsed=result, status_code=200)

    monkeypatch.setattr(bridge.measure_photo_exposure, "sync_detailed", slow_measure)
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "test-token")
    window.photos._success(first)
    window.photos._success(second)
    try:
        window.exposure_button.click()
        assert not window.exposure_button.isEnabled()
        assert not window.open_session_button.isEnabled()
        window.photo_grid.setCurrentRow(1)
        wait_until(lambda: window.photos._worker is None)
        assert window.photo_grid.item(0).data(256).exposure == result
        assert not isinstance(window.photo_grid.item(1).data(256).exposure, ExposureOut)
        assert window._selected_shot().shot_id == second_shot.shot_id
        assert "non ancora misurata" in window.details_label.text()
        window.photo_grid.setCurrentRow(0)
        assert "50.0/100" in window.details_label.text()
        assert "25.0%" in window.details_label.text()
        assert "non qualita' complessiva" in window.details_label.text()
        assert "non clipping del sensore RAW" in window.details_label.text()
    finally:
        window.close()
        connection.shutdown()


def test_measurement_requires_a_connected_idle_controller(qt_app: QApplication) -> None:
    controller = PhotoController()
    errors: list[str] = []
    controller.failed.connect(errors.append)
    try:
        controller.measure_exposure(uuid.uuid4())
        assert errors == ["Il nucleo non e' connesso."]
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller._active = True
        controller.measure_exposure(uuid.uuid4())
        assert errors[-1] == "Attendere la fine dell'operazione corrente."
        assert controller._worker is None
    finally:
        controller.shutdown()


def test_real_exposure_is_persisted_and_displayed_after_restart_without_originals(
    qt_app: QApplication, wait_until: Callable, tmp_path: Path
) -> None:
    if shutil.which("exiftool") is None:
        pytest.skip("ExifTool richiesto per importare tramite il nucleo reale")
    folder = tmp_path / "photos"
    folder.mkdir()
    for name, color in (("gray", (128, 128, 128)), ("white", (255, 255, 255))):
        with Image.new("RGB", (64, 32), color) as image:
            image.save(folder / f"{name}.png")
    originals = {path.name: path.read_bytes() for path in folder.iterdir()}
    data = tmp_path / "data"
    with _running_window(qt_app, wait_until, data) as first:
        first.select_folder(str(folder))
        first.import_button.click()
        wait_until(lambda: first.photo_grid.count() == 2 and not first._photo_busy)
        session_id = first.photos.session_id
        first.photo_grid.setCurrentRow(0)
        shot = first.photo_grid.item(0).data(256)
        assert not isinstance(shot.exposure, ExposureOut)
        first.exposure_button.click()
        wait_until(
            lambda: (
                isinstance(first.photo_grid.item(0).data(256).exposure, ExposureOut)
                and not first._photo_busy
            )
        )
        measured = first.photo_grid.item(0).data(256).exposure
        assert measured.score in {0, 100}
        assert "Esposizione anteprima (64x32)" in first.details_label.text()
        assert "non qualita' complessiva" in first.details_label.text()
        first.exposure_button.click()
        wait_until(lambda: not first._photo_busy)
        assert first.photo_grid.item(0).data(256).exposure.to_dict() == measured.to_dict()
    moved = tmp_path / "offline-originals"
    folder.rename(moved)
    with _running_window(qt_app, wait_until, data) as reopened:
        reopened.session_combo.setCurrentIndex(reopened.session_combo.findData(str(session_id)))
        reopened.open_session_button.click()
        wait_until(lambda: reopened.photo_grid.count() == 2 and not reopened._photo_busy)
        loaded_shot = reopened.photo_grid.item(0).data(256)
        assert loaded_shot.exposure.to_dict() == measured.to_dict()
        assert "non clipping del sensore RAW" in reopened.details_label.text()
        reopened.exposure_button.click()
        wait_until(lambda: not reopened._photo_busy)
        assert reopened.photo_grid.item(0).data(256).exposure.to_dict() == measured.to_dict()
        assert "IMPORTED" in reopened.import_status.text()
    assert {path.name: path.read_bytes() for path in moved.iterdir()} == originals
