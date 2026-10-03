import shutil
import subprocess
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
    BurstGroupingOut,
    BurstGroupOut,
    ReviewStatus,
    ShotOut,
)
from shotkeepr.desktop.connection import CoreConnection
from shotkeepr.desktop.photos import PhotoController, PhotoPage
from shotkeepr.desktop.window import MainWindow

from .test_exposure import _shot_with_metadata
from .test_sessions import _page, _running_window, _session


def _grouping(session_id: uuid.UUID) -> BurstGroupingOut:
    captured = datetime(2026, 10, 3, tzinfo=UTC)
    return BurstGroupingOut(
        session_id=session_id,
        gap_seconds=2,
        method_version="camera-time-bursts-v1",
        grouped_at=captured,
        ungrouped_shots=1,
        groups=[
            BurstGroupOut(
                group_id=uuid.uuid4(),
                camera_model="Test camera",
                camera_serial="CAM-1",
                shots=42,
                first_capture=captured,
                last_capture=captured,
            )
        ],
    )


def _failed_session(failure: str) -> SimpleNamespace:
    if failure == "network":
        raise httpx.ConnectError("private-token")
    return SimpleNamespace(
        parsed=ApiError(detail="catalogo offline") if failure == "api" else None,
        status_code=503,
    )


def test_grouping_runs_off_the_graphical_thread_and_reloads_only_after_success(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session()
    result = _grouping(session.session_id)
    pages: list[PhotoPage] = []
    received: list[BurstGroupingOut] = []
    ticks: list[bool] = []
    errors: list[str] = []
    requests: list[object] = []

    def slow_group(*args: object, **kwargs: object) -> SimpleNamespace:
        requests.append(kwargs["body"].gap_seconds)
        time.sleep(0.15)
        return SimpleNamespace(parsed=result, status_code=200)

    page = _page(session)
    monkeypatch.setattr(bridge.group_photo_bursts, "sync_detailed", slow_group)
    monkeypatch.setattr(
        bridge.get_photo_session,
        "sync_detailed",
        lambda *args, **kwargs: SimpleNamespace(parsed=session, status_code=200),
    )
    monkeypatch.setattr(
        bridge.list_photo_shots,
        "sync_detailed",
        lambda *args, **kwargs: SimpleNamespace(parsed=page.page, status_code=200),
    )
    monkeypatch.setattr(
        bridge.get_photo_thumbnail,
        "sync_detailed",
        lambda *args, **kwargs: SimpleNamespace(
            parsed=ApiError(detail="offline preview"), status_code=404
        ),
    )
    controller = PhotoController()
    controller._success(page)
    controller.page_received.connect(pages.append)
    controller.groups_received.connect(received.append)
    controller.failed.connect(errors.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.group_bursts(1.5)
        controller.group_bursts(1.5)
        QTimer.singleShot(20, lambda: ticks.append(not received))
        wait_until(lambda: bool(pages) and controller._worker is None)
        assert requests == [1.5]
        assert ticks == [True]
        assert received == [result]
        assert errors == ["Attendere la fine dell'operazione corrente."]
        assert controller.session_id == session.session_id
        assert controller._offset == 1
        assert controller.view_group_id is None
        assert not controller._active
    finally:
        controller.shutdown()


@pytest.mark.parametrize("failure", ["api", "network", "invalid"])
def test_grouping_errors_keep_the_current_session_and_controls_retryable(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    session = _session()
    session.grouping = _grouping(session.session_id)
    page = _page(session)
    _shot_with_metadata(page)
    original = page.page.items[0].shot_id

    def failed(*args: object, **kwargs: object) -> SimpleNamespace:
        if failure == "network":
            raise httpx.ConnectError("private-token")
        return SimpleNamespace(
            parsed=ApiError(detail="raggruppamento protetto") if failure == "api" else None,
            status_code=409,
        )

    monkeypatch.setattr(bridge.group_photo_bursts, "sync_detailed", failed)
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "private-token")
    window.photos._success(page)
    try:
        window.group_button.click()
        assert not window.group_button.isEnabled()
        assert not window.group_filter.isEnabled()
        wait_until(lambda: not window._photo_busy)
        assert window.photo_grid.item(0).data(256).shot_id == original
        assert window.photos.session_id == session.session_id
        assert window.photos._offset == 1
        assert window.group_filter.count() == 3
        assert window.group_button.isEnabled()
        assert window.statusBar().currentMessage()
        assert "private-token" not in window.statusBar().currentMessage()
    finally:
        window.close()
        connection.shutdown()


@pytest.mark.parametrize("previous_view", ["all", "group", "ungrouped"])
@pytest.mark.parametrize("failure", ["api", "network", "invalid"])
def test_failed_group_switch_restores_the_filter_and_preserves_the_previous_page(
    qt_app: QApplication,
    wait_until: Callable,
    monkeypatch: pytest.MonkeyPatch,
    previous_view: str,
    failure: str,
) -> None:
    session = _session()
    session.grouping = _grouping(session.session_id)
    page = _page(session)
    _shot_with_metadata(page)
    group_id = session.grouping.groups[0].group_id
    previous_group = group_id if previous_view == "group" else None
    previous_ungrouped = previous_view == "ungrouped"
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "test-token")
    window.photos._success(
        PhotoPage(page.session, page.page, page.thumbnails, previous_group, previous_ungrouped)
    )
    errors: list[str] = []
    window.photos.failed.connect(errors.append)
    monkeypatch.setattr(
        bridge.get_photo_session,
        "sync_detailed",
        lambda *args, **kwargs: _failed_session(failure),
    )
    try:
        selected = "ungrouped" if previous_view == "group" else str(group_id)
        window.group_filter.setCurrentIndex(window.group_filter.findData(selected))
        wait_until(lambda: not window._photo_busy)
        restored = (
            "ungrouped" if previous_ungrouped else str(previous_group) if previous_group else ""
        )
        assert window.group_filter.currentData() == restored
        assert window.photo_grid.count() == 1
        assert window.photo_grid.item(0).data(256).shot_id == page.page.items[0].shot_id
        assert window.photos.session_id == session.session_id
        assert window.photos.view_group_id == previous_group
        assert window.photos.view_ungrouped == previous_ungrouped
        assert window.photos._offset == 1
        assert len(errors) == 1
        assert window.statusBar().currentMessage() == errors[0]
        assert "private-token" not in errors[0]
        assert window.group_filter.isEnabled()
        assert window.load_more_button.isEnabled()
    finally:
        window.close()
        connection.shutdown()


@pytest.mark.parametrize("view", ["all", "group", "ungrouped"])
def test_load_more_retains_the_successfully_loaded_group_filter(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch, view: str
) -> None:
    session = _session()
    group = uuid.uuid4() if view == "group" else None
    ungrouped = view == "ungrouped"
    page = _page(session)
    next_page = _page(session, offset=1)
    requested: list[tuple[object, object, object]] = []

    def listing(*args: object, **kwargs: object) -> SimpleNamespace:
        requested.append((kwargs["group_id"], kwargs["ungrouped"], kwargs["offset"]))
        return SimpleNamespace(parsed=next_page.page, status_code=200)

    monkeypatch.setattr(
        bridge.get_photo_session,
        "sync_detailed",
        lambda *args, **kwargs: SimpleNamespace(parsed=session, status_code=200),
    )
    monkeypatch.setattr(bridge.list_photo_shots, "sync_detailed", listing)
    monkeypatch.setattr(
        bridge.get_photo_thumbnail,
        "sync_detailed",
        lambda *args, **kwargs: SimpleNamespace(
            parsed=ApiError(detail="no thumbnail"), status_code=404
        ),
    )
    controller = PhotoController()
    errors: list[str] = []
    controller.failed.connect(errors.append)
    controller._success(PhotoPage(page.session, page.page, page.thumbnails, group, ungrouped))
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.load_more()
        wait_until(lambda: controller._worker is None)
        assert requested == [(group, ungrouped, 1)]
        assert not errors
        assert controller.view_group_id == group
        assert controller.view_ungrouped == ungrouped
        assert controller.session_id == session.session_id
        assert controller._offset == 2
    finally:
        controller.shutdown()


def test_grouping_requires_a_connected_open_session(qt_app: QApplication) -> None:
    controller = PhotoController()
    errors: list[str] = []
    controller.failed.connect(errors.append)
    try:
        controller.group_bursts(2)
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.group_bursts(2)
        assert len(errors) == 2
        assert controller._worker is None
    finally:
        controller.shutdown()


@pytest.mark.parametrize(
    ("failure", "detail"),
    [
        ("api", "catalogo offline"),
        ("network", "Nucleo non raggiungibile"),
        ("invalid", "Risposta del catalogo non compatibile"),
    ],
)
def test_saved_grouping_with_a_failed_refresh_is_not_reported_as_a_failed_mutation(
    qt_app: QApplication,
    wait_until: Callable,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    detail: str,
) -> None:
    session = _session()
    page = _page(session)
    result = _grouping(session.session_id)
    monkeypatch.setattr(
        bridge.group_photo_bursts,
        "sync_detailed",
        lambda *args, **kwargs: SimpleNamespace(parsed=result, status_code=200),
    )
    monkeypatch.setattr(
        bridge.get_photo_session,
        "sync_detailed",
        lambda *args, **kwargs: _failed_session(failure),
    )
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "test-token")
    window.photos._success(page)
    errors: list[str] = []
    received: list[BurstGroupingOut] = []
    window.photos.failed.connect(errors.append)
    window.photos.groups_received.connect(received.append)
    try:
        window.group_button.click()
        wait_until(lambda: window.photos._worker is None)
        assert received == [result]
        assert len(errors) == 1
        assert "Raffiche salvate, ma ricaricamento non riuscito" in errors[0]
        assert detail in errors[0]
        assert "private-token" not in errors[0]
        assert window.statusBar().currentMessage() == errors[0]
        assert window.photo_grid.item(0).data(256).shot_id == page.page.items[0].shot_id
        assert window.photos.session_id == session.session_id
        assert window.group_button.isEnabled()
        assert not window.photos._group_refresh_expected
        assert not window.photos._group_reload_pending
    finally:
        window.close()
        connection.shutdown()


def _pictures_with_metadata(folder: Path, group_size: int, executable: str) -> None:
    folder.mkdir()
    paths = []
    for index in range(group_size + 2):
        path = folder / f"photo-{index:03d}.jpg"
        with Image.new(
            "RGB", (64, 32), (index * 5 % 256, index * 7 % 256, index * 11 % 256)
        ) as image:
            image.save(path)
        paths.append(path)
    written = subprocess.run(  # noqa: S603 -- resolved test executable, no shell
        [
            executable,
            "-config",
            "",
            "-overwrite_original",
            "-Model=Test camera",
            "-EXIF:SerialNumber=CAM-1",
            "-DateTimeOriginal=2026:10:03 10:00:00",
            "-OffsetTimeOriginal=+00:00",
            *[str(path) for path in paths[: group_size + 1]],
        ],
        capture_output=True,
        check=True,
    )
    assert not written.stderr
    subprocess.run(  # noqa: S603 -- resolved test executable, no shell
        [
            executable,
            "-config",
            "",
            "-overwrite_original",
            "-DateTimeOriginal=2026:10:03 10:00:30",
            str(paths[group_size]),
        ],
        capture_output=True,
        check=True,
    )


def _assert_group_pagination(
    window: MainWindow, wait_until: Callable, group_id: uuid.UUID, group_size: int
) -> None:
    window.group_filter.setCurrentIndex(window.group_filter.findData(str(group_id)))
    wait_until(lambda: window.photos.view_group_id == group_id and not window._photo_busy)
    assert window.photo_grid.count() == bridge.PAGE_SIZE
    assert all(
        window.photo_grid.item(index).data(256).group_id == group_id
        for index in range(bridge.PAGE_SIZE)
    )
    assert window.load_more_button.isEnabled()
    window.load_more_button.click()
    wait_until(lambda: window.photo_grid.count() == group_size and not window._photo_busy)
    assert not window.load_more_button.isEnabled()
    assert window.photos._offset == group_size
    window.group_filter.setCurrentIndex(window.group_filter.findData("ungrouped"))
    wait_until(lambda: window.photos.view_ungrouped and not window._photo_busy)
    assert window.photo_grid.count() == 2
    assert all(window.photo_grid.item(index).data(256).group_id is None for index in range(2))
    assert not window.load_more_button.isEnabled()


def _keep_shot_for_regrouping(window: MainWindow, wait_until: Callable) -> ShotOut:
    window.photo_grid.setCurrentRow(1)
    window.review_combo.setCurrentIndex(window.review_combo.findData("KEEP"))
    window.review_button.click()
    wait_until(lambda: not window._photo_busy)
    saved_shot = window._selected_shot()
    assert saved_shot is not None
    assert saved_shot.review.status == ReviewStatus.KEEP
    assert saved_shot.files[0].metadata.camera_model == "Test camera"
    assert saved_shot.files[0].metadata.camera_serial == "CAM-1"
    assert saved_shot.capture_time is not None
    return saved_shot


def test_real_grouping_pagination_and_review_persist_after_core_restart_without_originals(
    qt_app: QApplication, wait_until: Callable, tmp_path: Path
) -> None:
    executable = shutil.which("exiftool")
    if executable is None:
        pytest.skip("ExifTool required for real photographic import")
    folder = tmp_path / "photos"
    group_size = bridge.PAGE_SIZE + 2
    _pictures_with_metadata(folder, group_size, executable)
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
        wait_for_catalog(
            lambda: first.photo_grid.count() == bridge.PAGE_SIZE and not first._photo_busy
        )
        session_id = first.photos.session_id
        saved_shot = _keep_shot_for_regrouping(first, wait_for_catalog)
        assert first.group_button.isEnabled()
        assert first.burst_gap.value() == 2
        first.group_button.click()
        wait_for_catalog(lambda: first.photos._worker is None)
        assert first.group_filter.count() == 3, first.import_status.text()
        group_id = uuid.UUID(first.group_filter.itemData(2))
        assert "Raffica" in first.photo_grid.item(1).text()
        _assert_group_pagination(first, wait_for_catalog, group_id, group_size)
    moved = tmp_path / "offline-originals"
    folder.rename(moved)
    with _running_window(qt_app, wait_for_catalog, data) as reopened:
        reopened.photos.failed.connect(errors.append)
        reopened.session_combo.setCurrentIndex(reopened.session_combo.findData(str(session_id)))
        reopened.open_session_button.click()
        wait_for_catalog(
            lambda: reopened.photo_grid.count() == bridge.PAGE_SIZE and not reopened._photo_busy
        )
        assert reopened.group_filter.count() == 3
        assert reopened.group_filter.itemData(2) == str(group_id)
        assert reopened.burst_gap.value() == 2
        reopened.group_filter.setCurrentIndex(2)
        wait_for_catalog(
            lambda: reopened.photos.view_group_id == group_id and not reopened._photo_busy
        )
        kept = next(
            reopened.photo_grid.item(index).data(256)
            for index in range(reopened.photo_grid.count())
            if reopened.photo_grid.item(index).data(256).shot_id == saved_shot.shot_id
        )
        assert kept.review.to_dict() == saved_shot.review.to_dict()
        assert "IMPORTED" in reopened.import_status.text()
        reopened.burst_gap.setValue(0.5)
        reopened.group_button.click()
        wait_for_catalog(
            lambda: reopened.photos.view_group_id is None and reopened.photos._worker is None
        )
        assert reopened.group_filter.itemData(2) == str(group_id)
        assert reopened.burst_gap.value() == 0.5
    assert not errors, errors
    assert {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in moved.iterdir()
    } == originals
