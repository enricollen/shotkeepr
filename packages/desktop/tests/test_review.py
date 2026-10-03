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
from PySide6.QtWidgets import QApplication, QMessageBox

from shotkeepr.desktop import photos as bridge
from shotkeepr.desktop.api_client.models import ApiError, ReviewOut, ReviewStatus, XmpOut
from shotkeepr.desktop.connection import CoreConnection
from shotkeepr.desktop.photos import PhotoController
from shotkeepr.desktop.window import MainWindow

from .test_exposure import _shot_with_metadata
from .test_sessions import _page, _running_window, _session


def _review(shot_id: uuid.UUID, status: ReviewStatus = ReviewStatus.KEEP) -> ReviewOut:
    return ReviewOut(shot_id=shot_id, status=status, updated_at=datetime.now(UTC))


def test_manual_review_waits_for_persistence_without_blocking_qt(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session()
    first, second = _page(session), _page(session, offset=1)
    first_shot, second_shot = _shot_with_metadata(first), _shot_with_metadata(second)
    saved = _review(first_shot.shot_id)

    def slow_save(*args: object, **kwargs: object) -> SimpleNamespace:
        time.sleep(0.15)
        return SimpleNamespace(parsed=saved, status_code=200)

    monkeypatch.setattr(bridge.set_photo_review, "sync_detailed", slow_save)
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "test-token")
    window.photos._success(first)
    window.photos._success(second)
    ticks: list[bool] = []
    try:
        window.review_combo.setCurrentIndex(window.review_combo.findData("KEEP"))
        window.review_button.click()
        assert "Da rivedere" in window.photo_grid.item(0).text()
        assert not window.review_button.isEnabled()
        QTimer.singleShot(20, lambda: ticks.append(window._photo_busy))
        window.photo_grid.setCurrentRow(1)
        wait_until(lambda: not window._photo_busy)
        assert ticks == [True]
        assert window.photo_grid.item(0).data(256).review == saved
        assert "Tenuta" in window.photo_grid.item(0).text()
        assert "Da rivedere" in window.photo_grid.item(1).text()
        assert window._selected_shot().shot_id == second_shot.shot_id
        assert "Da rivedere (revisione manuale)" in window.details_label.text()
        assert window.photos.session_id == session.session_id
        assert window.photos._offset == 2
        assert window.review_button.isEnabled()
    finally:
        window.close()
        connection.shutdown()


@pytest.mark.parametrize("failure", ["api", "network", "invalid"])
def test_failed_save_never_changes_the_displayed_status(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def failed(*args: object, **kwargs: object) -> SimpleNamespace:
        if failure == "network":
            raise httpx.ConnectError("private-token")
        parsed = ApiError(detail="salvataggio non riuscito") if failure == "api" else None
        return SimpleNamespace(parsed=parsed, status_code=503)

    monkeypatch.setattr(bridge.set_photo_review, "sync_detailed", failed)
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "private-token")
    page = _page(_session())
    _shot_with_metadata(page)
    window.photos._success(page)
    try:
        window.review_combo.setCurrentIndex(window.review_combo.findData("REJECT"))
        window.review_button.click()
        wait_until(lambda: not window._photo_busy)
        assert "Da rivedere" in window.photo_grid.item(0).text()
        assert window.statusBar().currentMessage()
        assert "private-token" not in window.statusBar().currentMessage()
        assert window.review_button.isEnabled()
    finally:
        window.close()
        connection.shutdown()


def test_export_requires_confirmation_and_uses_the_saved_not_edited_state(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "test-token")
    page = _page(_session())
    shot = _shot_with_metadata(page)
    shot.review = _review(shot.shot_id)
    window.photos._success(page)
    requested: list[dict[str, object]] = []

    def export(*args: object, **kwargs: object) -> SimpleNamespace:
        requested.append(kwargs["body"].to_dict())
        return SimpleNamespace(
            parsed=XmpOut(
                shot_id=shot.shot_id, status=ReviewStatus.KEEP, paths=["/photos/photo.xmp"]
            ),
            status_code=200,
        )

    monkeypatch.setattr(bridge.export_photo_xmp, "sync_detailed", export)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    try:
        window.xmp_button.click()
        assert requested == []
        window.review_combo.setCurrentIndex(window.review_combo.findData("REJECT"))
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        window.xmp_button.click()
        wait_until(lambda: not window._photo_busy)
        assert requested == [{"confirm": True, "expected_status": "KEEP"}]
        assert "XMP esportato (Tenuta): /photos/photo.xmp" in window.statusBar().currentMessage()
    finally:
        window.close()
        connection.shutdown()


def test_filter_only_hides_loaded_shots_and_retains_pagination(qt_app: QApplication) -> None:
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    session = _session()
    first, second = _page(session), _page(session, offset=1)
    kept = _shot_with_metadata(first)
    _shot_with_metadata(second)
    kept.review = _review(kept.shot_id)
    try:
        window.photos._success(first)
        window.photos._success(second)
        window.review_filter.setCurrentIndex(window.review_filter.findData("KEEP"))
        assert window.photo_grid.count() == 2
        assert not window.photo_grid.item(0).isHidden()
        assert window.photo_grid.item(1).isHidden()
        assert window.photos._offset == 2
        window.review_filter.setCurrentIndex(window.review_filter.findData("REJECT"))
        assert all(window.photo_grid.item(index).isHidden() for index in range(2))
        assert window._selected_shot() is None
        assert not window.review_button.isEnabled()
        window.review_filter.setCurrentIndex(0)
        assert window._selected_shot() is not None
        assert window.photos._offset == 2
    finally:
        window.close()
        connection.shutdown()


def test_export_network_failure_does_not_claim_no_sidecars_were_written(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*args: object, **kwargs: object) -> None:
        raise httpx.ReadTimeout("private-token")

    monkeypatch.setattr(bridge.export_photo_xmp, "sync_detailed", timeout)
    controller = PhotoController()
    errors: list[str] = []
    controller.failed.connect(errors.append)
    try:
        controller.configure("http://127.0.0.1:12345", "private-token")
        controller.export_xmp(uuid.uuid4(), ReviewStatus.KEEP)
        wait_until(lambda: controller._worker is None)
        assert "Esito export XMP non noto" in errors[0]
        assert "private-token" not in errors[0]
    finally:
        controller.shutdown()


def test_real_review_and_export_survive_core_restart(
    qt_app: QApplication, wait_until: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if shutil.which("exiftool") is None:
        pytest.skip("ExifTool required for real import and XMP export")
    source = tmp_path / "photos"
    source.mkdir()
    photo = source / "photo.png"
    with Image.new("RGB", (32, 16), "gray") as image:
        image.save(photo)
    original, timestamp = photo.read_bytes(), photo.stat().st_mtime_ns
    data = tmp_path / "catalog"
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    with _running_window(qt_app, wait_until, data) as window:
        window.select_folder(str(source))
        window.import_button.click()
        wait_until(lambda: window.photo_grid.count() == 1 and not window._photo_busy)
        session_id = window.photos.session_id
        window.review_combo.setCurrentIndex(window.review_combo.findData("KEEP"))
        window.review_button.click()
        wait_until(lambda: not window._photo_busy)
        assert "Tenuta" in window.photo_grid.item(0).text()
        saved = window.photo_grid.item(0).data(256).review.to_dict()
        window.xmp_button.click()
        wait_until(lambda: not window._photo_busy)
        assert photo.with_suffix(".xmp").is_file()
        assert "XMP esportato" in window.statusBar().currentMessage()
    with _running_window(qt_app, wait_until, data) as reopened:
        reopened.session_combo.setCurrentIndex(reopened.session_combo.findData(str(session_id)))
        reopened.open_session_button.click()
        wait_until(lambda: reopened.photo_grid.count() == 1 and not reopened._photo_busy)
        assert reopened.photo_grid.item(0).data(256).review.to_dict() == saved
        assert "Tenuta (revisione manuale)" in reopened.details_label.text()
        assert "IMPORTED" in reopened.import_status.text()
    assert photo.read_bytes() == original
    assert photo.stat().st_mtime_ns == timestamp
