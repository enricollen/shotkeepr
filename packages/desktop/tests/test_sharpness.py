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
from shotkeepr.desktop.api_client.models import ApiError, SharpnessOut
from shotkeepr.desktop.connection import CoreConnection
from shotkeepr.desktop.photos import PhotoController
from shotkeepr.desktop.window import MainWindow

from .test_exposure import _measurement as _exposure
from .test_exposure import _shot_with_metadata
from .test_sessions import _page, _running_window, _session


def _measurement(shot_id: uuid.UUID) -> SharpnessOut:
    return SharpnessOut(
        shot_id=shot_id,
        source_fingerprint="a" * 64,
        preview_sha256="b" * 64,
        analyzer_version="preview-luma-laplacian-v1",
        measured_at=datetime.now(UTC),
        width=64,
        height=32,
        laplacian_variance=0.05,
        gradient_energy=0.025,
    )


def test_sharpness_does_not_block_qt_and_updates_only_the_requested_shot(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session()
    first, second = _page(session), _page(session, offset=1)
    first_shot, second_shot = _shot_with_metadata(first), _shot_with_metadata(second)
    result = _measurement(first_shot.shot_id)
    exposure = _exposure(first_shot.shot_id)
    first_shot.exposure = exposure

    def slow_measure(*args: object, **kwargs: object) -> SimpleNamespace:
        time.sleep(0.15)
        return SimpleNamespace(parsed=result, status_code=200)

    monkeypatch.setattr(bridge.measure_photo_sharpness, "sync_detailed", slow_measure)
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "test-token")
    window.photos._success(first)
    window.photos._success(second)
    ticks: list[bool] = []
    try:
        window.sharpness_button.click()
        assert not window.sharpness_button.isEnabled()
        assert not window.exposure_button.isEnabled()
        QTimer.singleShot(20, lambda: ticks.append(window._photo_busy))
        window.photo_grid.setCurrentRow(1)
        wait_until(lambda: window.photos._worker is None)
        assert ticks == [True]
        assert window.photo_grid.item(0).data(256).sharpness == result
        assert window.photo_grid.item(0).data(256).exposure == exposure
        assert window._selected_shot().shot_id == second_shot.shot_id
        assert "Nitidezza anteprima: non ancora misurata" in window.details_label.text()
        assert window.photos._offset == 2
        assert window.photos.session_id == session.session_id
        window.photo_grid.setCurrentRow(0)
        assert "Varianza Laplaciano: 0.05" in window.details_label.text()
        assert "Energia gradienti: 0.025" in window.details_label.text()
        assert "non fuoco del soggetto o voto fotografico" in window.details_label.text()
        assert window.sharpness_button.isEnabled()
    finally:
        window.close()
        connection.shutdown()


@pytest.mark.parametrize("failure", ["api", "network", "invalid"])
def test_measurement_errors_preserve_saved_results_and_allow_retry(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def failed(*args: object, **kwargs: object) -> SimpleNamespace:
        if failure == "network":
            raise httpx.ConnectError("private-token")
        return SimpleNamespace(
            parsed=ApiError(detail="anteprima non disponibile") if failure == "api" else None,
            status_code=409,
        )

    monkeypatch.setattr(bridge.measure_photo_sharpness, "sync_detailed", failed)
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "private-token")
    page = _page(_session())
    shot = _shot_with_metadata(page)
    saved = _measurement(shot.shot_id)
    shot.sharpness = saved
    window.photos._success(page)
    try:
        window.sharpness_button.click()
        wait_until(lambda: window.photos._worker is None)
        assert window.photo_grid.count() == 1
        assert window.photo_grid.item(0).data(256).sharpness == saved
        assert "Varianza Laplaciano: 0.05" in window.details_label.text()
        assert window.sharpness_button.isEnabled()
        assert window.statusBar().currentMessage()
        assert "private-token" not in window.statusBar().currentMessage()
    finally:
        window.close()
        connection.shutdown()


def test_measurement_requires_a_connected_idle_controller(qt_app: QApplication) -> None:
    controller = PhotoController()
    errors: list[str] = []
    controller.failed.connect(errors.append)
    try:
        controller.measure_sharpness(uuid.uuid4())
        assert errors == ["Il nucleo non e' connesso."]
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller._active = True
        controller.measure_sharpness(uuid.uuid4())
        assert errors[-1] == "Attendere la fine dell'operazione corrente."
        assert controller._worker is None
    finally:
        controller.shutdown()


def test_details_remain_scrollable_with_both_measurements_at_minimum_display(
    qt_app: QApplication,
) -> None:
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    page = _page(_session())
    shot = _shot_with_metadata(page)
    shot.exposure, shot.sharpness = _exposure(shot.shot_id), _measurement(shot.shot_id)
    try:
        window.resize(1100, 640)
        window.show()
        window.photos._success(page)
        qt_app.processEvents()
        assert window.width() <= 1366 and window.height() <= 768
        assert window.details_scroll.widget() == window.details_label
        assert window.details_scroll.verticalScrollBar().maximum() > 0
        assert "50.0/100" in window.details_label.text()
        assert "Varianza Laplaciano" in window.details_label.text()
    finally:
        window.close()
        connection.shutdown()


def test_real_gui_sharpness_persists_after_restart_without_originals(
    qt_app: QApplication, wait_until: Callable, tmp_path: Path
) -> None:
    if shutil.which("exiftool") is None:
        pytest.skip("ExifTool required for photographic import")
    folder = tmp_path / "photos"
    folder.mkdir()
    original = folder / "gray.png"
    with Image.new("RGB", (64, 32), "gray") as image:
        image.save(original)
    before, timestamp = original.read_bytes(), original.stat().st_mtime_ns
    data = tmp_path / "catalog"
    with _running_window(qt_app, wait_until, data) as first:
        first.select_folder(str(folder))
        first.import_button.click()
        wait_until(lambda: first.photo_grid.count() == 1 and not first._photo_busy)
        session_id = first.photos.session_id
        first.sharpness_button.click()
        wait_until(
            lambda: (
                isinstance(first.photo_grid.item(0).data(256).sharpness, SharpnessOut)
                and not first._photo_busy
            )
        )
        measured = first.photo_grid.item(0).data(256).sharpness
        assert measured.laplacian_variance == 0
        assert "non fuoco del soggetto" in first.details_label.text()
    moved = tmp_path / "offline-originals"
    folder.rename(moved)
    with _running_window(qt_app, wait_until, data) as reopened:
        reopened.session_combo.setCurrentIndex(reopened.session_combo.findData(str(session_id)))
        reopened.open_session_button.click()
        wait_until(lambda: reopened.photo_grid.count() == 1 and not reopened._photo_busy)
        assert reopened.photo_grid.item(0).data(256).sharpness.to_dict() == measured.to_dict()
        reopened.sharpness_button.click()
        wait_until(lambda: not reopened._photo_busy)
        assert reopened.photo_grid.item(0).data(256).sharpness.to_dict() == measured.to_dict()
        assert "IMPORTED" in reopened.import_status.text()
    assert (moved / "gray.png").read_bytes() == before
    assert (moved / "gray.png").stat().st_mtime_ns == timestamp
