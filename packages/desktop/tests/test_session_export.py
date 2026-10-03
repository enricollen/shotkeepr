import json
import shutil
import subprocess
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from shotkeepr.desktop import photos as bridge
from shotkeepr.desktop.api_client.models import (
    ApiError,
    ReviewStatus,
    SessionOut,
    ShotOut,
    XmpOut,
    XmpRequest,
)
from shotkeepr.desktop.connection import CoreConnection
from shotkeepr.desktop.photos import PhotoController, PhotoPage, XmpBatch
from shotkeepr.desktop.window import MainWindow

from .test_review import _review
from .test_session_measurements import _catalog
from .test_sessions import _page, _running_window


def _export_catalog(
    monkeypatch: pytest.MonkeyPatch, count: int
) -> tuple[
    SessionOut, list[ShotOut], list[tuple[int, int]], list[tuple[uuid.UUID, dict[str, object]]]
]:
    session, shots, requests = _catalog(monkeypatch, count)
    statuses = (ReviewStatus.KEEP, ReviewStatus.REJECT, ReviewStatus.REVIEW)
    for index, shot in enumerate(shots):
        shot.review = _review(shot.shot_id, statuses[index % len(statuses)])
    exported: list[tuple[uuid.UUID, dict[str, object]]] = []

    def export(shot_id: uuid.UUID, *, body: XmpRequest, **kwargs: object) -> SimpleNamespace:
        exported.append((shot_id, body.to_dict()))
        return SimpleNamespace(
            parsed=XmpOut(
                shot_id=shot_id, status=body.expected_status, paths=[f"/photos/{shot_id}.xmp"]
            ),
            status_code=200,
        )

    monkeypatch.setattr(bridge.export_photo_xmp, "sync_detailed", export)
    return session, shots, requests, exported


def test_exports_all_session_pages_using_saved_statuses_without_changing_the_view(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    count = bridge.PAGE_SIZE + 3
    session, shots, requests, exported = _export_catalog(monkeypatch, count)
    controller = PhotoController()
    page = _page(session, offset=5)
    group = uuid.uuid4()
    controller._success(PhotoPage(session, page.page, page.thumbnails, group))
    received: list[XmpBatch] = []
    errors: list[str] = []
    progress: list[tuple[int, int]] = []
    controller.xmp_session_finished.connect(received.append)
    controller.failed.connect(errors.append)
    controller.xmp_progress.connect(lambda done, total: progress.append((done, total)))
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.export_session()
        controller.export_session()
        wait_until(lambda: bool(received) and controller._worker is None)
        assert received == [XmpBatch(session.session_id, count, count, count, False)]
        assert exported == [
            (shot.shot_id, {"confirm": True, "expected_status": shot.review.status.value})
            for shot in shots
        ]
        assert requests == [(0, bridge.PAGE_SIZE), (bridge.PAGE_SIZE, bridge.PAGE_SIZE)]
        assert progress == [(index, count) for index in range(count + 1)]
        assert errors == ["Attendere la fine dell'operazione corrente."]
        assert controller.session_id == session.session_id
        assert controller._offset == 6 and controller.view_group_id == group
        assert not controller._active and controller._job_id is None
    finally:
        controller.shutdown()


@pytest.mark.parametrize(
    "failure",
    [
        "api",
        "network",
        "invalid",
        "wrong-shot",
        "wrong-status",
        "empty-paths",
        "blank-path",
        "duplicates",
        "invalid-path-type",
        "non-list-paths",
    ],
)
def test_errors_report_only_confirmed_writes_and_never_retry_automatically(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    session, shots, _requests, exported = _export_catalog(monkeypatch, 3)
    original_export = bridge.export_photo_xmp.sync_detailed

    def failing_export(
        shot_id: uuid.UUID, *, body: XmpRequest, **kwargs: object
    ) -> SimpleNamespace:
        if shot_id == shots[0].shot_id:
            return original_export(shot_id, body=body, **kwargs)
        exported.append((shot_id, body.to_dict()))
        if failure == "network":
            raise httpx.ReadTimeout("private-token")
        if failure == "api":
            return SimpleNamespace(parsed=ApiError(detail="Stato modificato"), status_code=409)
        if failure == "invalid":
            return SimpleNamespace(parsed=None, status_code=200)
        if failure in {"invalid-path-type", "non-list-paths"}:
            malformed = XmpOut.from_dict(
                {
                    "shot_id": str(shot_id),
                    "status": body.expected_status.value,
                    "paths": [None] if failure == "invalid-path-type" else "not-a-list",
                }
            )
            return SimpleNamespace(parsed=malformed, status_code=200)
        paths = [f"/photos/{shot_id}.xmp"]
        if failure == "empty-paths":
            paths = []
        elif failure == "blank-path":
            paths = [" "]
        elif failure == "duplicates":
            paths *= 2
        result = XmpOut(
            shot_id=uuid.uuid4() if failure == "wrong-shot" else shot_id,
            status=ReviewStatus.KEEP if failure == "wrong-status" else body.expected_status,
            paths=paths,
        )
        return SimpleNamespace(parsed=result, status_code=200)

    monkeypatch.setattr(bridge.export_photo_xmp, "sync_detailed", failing_export)
    controller = PhotoController()
    controller._success(_page(session))
    received: list[XmpBatch] = []
    errors: list[str] = []
    controller.xmp_session_finished.connect(received.append)
    controller.failed.connect(errors.append)
    try:
        controller.configure("http://127.0.0.1:12345", "private-token")
        controller.export_session()
        wait_until(lambda: controller._worker is None)
        assert not received
        assert len(exported) == 2 and len(errors) == 1
        assert "1/3 scatti confermati, 1 sidecar" in errors[0]
        assert "Nessun rollback" in errors[0]
        assert "private-token" not in errors[0]
        if failure == "network":
            assert "Esito export XMP non noto" in errors[0]
        elif failure == "api":
            assert "Stato modificato" in errors[0]
        assert controller._offset == 1
    finally:
        controller.shutdown()


@pytest.mark.parametrize("invalid", ["missing", "wrong-shot"])
def test_missing_or_mismatched_reviews_are_not_exported_as_default_states(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    session, shots, _requests, exported = _export_catalog(monkeypatch, 1)
    shots[0].review = None if invalid == "missing" else _review(uuid.uuid4())
    controller = PhotoController()
    controller._success(_page(session))
    errors: list[str] = []
    controller.failed.connect(errors.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.export_session()
        wait_until(lambda: controller._worker is None)
        assert not exported and len(errors) == 1
        assert "0/1 scatti confermati" in errors[0]
    finally:
        controller.shutdown()


def test_cancellation_waits_for_the_in_flight_export_and_preserves_completed_sidecars(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, shots, _requests, exported = _export_catalog(monkeypatch, 2)
    entered, release = threading.Event(), threading.Event()
    original_export = bridge.export_photo_xmp.sync_detailed

    def blocked(shot_id: uuid.UUID, *, body: XmpRequest, **kwargs: object) -> SimpleNamespace:
        entered.set()
        assert release.wait(5)
        return original_export(shot_id, body=body, **kwargs)

    monkeypatch.setattr(bridge.export_photo_xmp, "sync_detailed", blocked)
    controller = PhotoController()
    controller._success(_page(session))
    received: list[XmpBatch] = []
    errors: list[str] = []
    ticks: list[bool] = []
    controller.xmp_session_finished.connect(received.append)
    controller.failed.connect(errors.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.export_session()
        QTimer.singleShot(0, lambda: ticks.append(controller.exporting_session))
        wait_until(entered.is_set)
        assert ticks == [True]
        controller.cancel_session_export()
        assert controller.export_cancel_requested
        release.set()
        wait_until(lambda: controller._worker is None)
        assert received == [XmpBatch(session.session_id, 1, 2, 1, True)]
        assert [shot_id for shot_id, _body in exported] == [shots[0].shot_id]
        assert not errors and not controller.exporting_session
    finally:
        release.set()
        controller.shutdown()


@pytest.mark.parametrize("count", [0, 1])
def test_empty_sessions_and_invalid_pagination_never_trigger_unintended_writes(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    session, _shots, _requests, exported = _export_catalog(monkeypatch, count)
    if count:
        monkeypatch.setattr(
            bridge.list_photo_shots,
            "sync_detailed",
            lambda *args, **kwargs: SimpleNamespace(
                parsed=bridge.ShotPageOut(items=[], total=count, offset=0, limit=bridge.PAGE_SIZE),
                status_code=200,
            ),
        )
    controller = PhotoController()
    controller._success(_page(session))
    received: list[XmpBatch] = []
    errors: list[str] = []
    controller.xmp_session_finished.connect(received.append)
    controller.failed.connect(errors.append)
    try:
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.export_session()
        wait_until(lambda: controller._worker is None)
        assert not exported
        if count:
            assert not received and len(errors) == 1
        else:
            assert not errors
            assert received == [XmpBatch(session.session_id, 0, 0, 0, False)]
    finally:
        controller.shutdown()


def test_shutdown_ignores_late_batch_progress(qt_app: QApplication) -> None:
    controller = PhotoController()
    received: list[tuple[int, int]] = []
    controller.xmp_progress.connect(lambda done, total: received.append((done, total)))
    controller.measurement_progress.connect(lambda done, total: received.append((done, total)))
    controller.shutdown()
    controller._batch_progress(1, 2)
    assert not received


def test_export_requires_a_connected_open_idle_session(qt_app: QApplication) -> None:
    controller = PhotoController()
    errors: list[str] = []
    controller.failed.connect(errors.append)
    try:
        controller.export_session()
        controller.configure("http://127.0.0.1:12345", "test-token")
        controller.export_session()
        controller._session_id = uuid.uuid4()
        controller._active = True
        controller.export_session()
        controller.cancel_session_export()
        assert len(errors) == 4 and controller._worker is None
    finally:
        controller.shutdown()


def test_gui_confirmation_is_session_wide_and_defaults_to_no(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, shots, _requests, exported = _export_catalog(monkeypatch, 3)
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "test-token")
    page = _page(session)
    window.photos._success(PhotoPage(session, page.page, (bridge.Thumbnail(shots[0], None),)))
    confirmations: list[tuple[str, object]] = []

    def deny(*args: object) -> QMessageBox.StandardButton:
        confirmations.append((args[2], args[-1]))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", deny)
    try:
        window.review_combo.setCurrentIndex(window.review_combo.findData("REJECT"))
        window.export_session_button.click()
        assert not exported and window.photos._worker is None
        assert "TUTTI" in confirmations[0][0] and "Da rivedere" in confirmations[0][0]
        assert confirmations[0][1] == QMessageBox.StandardButton.No
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        window.export_session_button.click()
        wait_until(lambda: window.photos._worker is None)
        assert exported[0][1]["expected_status"] == "KEEP"
        assert len(exported) == 3
        assert window.photo_grid.count() == 1 and window.photos._offset == 1
        assert "Export completato: 3/3 scatti, 3 sidecar" in window.import_status.text()
        assert window.import_progress.value() == 3
        assert window.export_session_button.isEnabled()
        assert not window.cancel_export_button.isEnabled()
    finally:
        window.close()
        connection.shutdown()


def test_gui_stop_restores_controls_without_claiming_a_rollback(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, _shots, _requests, _exported = _export_catalog(monkeypatch, 2)
    entered, release = threading.Event(), threading.Event()
    original_export = bridge.export_photo_xmp.sync_detailed

    def blocked(shot_id: uuid.UUID, *, body: XmpRequest, **kwargs: object) -> SimpleNamespace:
        entered.set()
        assert release.wait(5)
        return original_export(shot_id, body=body, **kwargs)

    monkeypatch.setattr(bridge.export_photo_xmp, "sync_detailed", blocked)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window._connected = True
    window.photos.configure("http://127.0.0.1:12345", "test-token")
    window.photos._success(_page(session))
    try:
        window.export_session_button.click()
        wait_until(entered.is_set)
        assert not window.export_session_button.isEnabled()
        assert not window.measure_session_button.isEnabled()
        assert window.cancel_export_button.isEnabled()
        window.cancel_export_button.click()
        assert not window.cancel_export_button.isEnabled()
        release.set()
        wait_until(lambda: window.photos._worker is None)
        assert "Export annullato: 1/2 scatti" in window.import_status.text()
        assert "gia' scritti restano" in window.import_status.text()
        assert window.export_session_button.isEnabled()
    finally:
        release.set()
        window.close()
        connection.shutdown()


def _read_xmp(executable: str, source: Path) -> list[dict[str, object]]:
    result = subprocess.run(  # noqa: S603 -- resolved test executable, no shell
        [
            executable,
            "-config",
            "",
            "-json",
            "-n",
            "-XMP:Rating",
            "-XMP:Label",
            *map(str, sorted(source.glob("*.xmp"))),
        ],
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_real_session_export_writes_saved_states_and_preserves_originals(
    qt_app: QApplication, wait_until: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = shutil.which("exiftool")
    if executable is None:
        pytest.skip("ExifTool required for real import and XMP export")
    source = tmp_path / "photos"
    source.mkdir()
    for name, color in (("first", "gray"), ("second", "white")):
        with Image.new("RGB", (32, 16), color) as image:
            image.save(source / f"{name}.png")
    originals = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in source.iterdir()
    }
    errors: list[str] = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)

    def wait_for_catalog(predicate: Callable[[], bool]) -> None:
        wait_until(lambda: bool(errors) or predicate())
        assert not errors, errors

    with _running_window(qt_app, wait_for_catalog, tmp_path / "catalog") as window:
        window.photos.failed.connect(errors.append)
        window.select_folder(str(source))
        window.import_button.click()
        wait_for_catalog(lambda: window.photo_grid.count() == 2 and not window._photo_busy)
        window.review_combo.setCurrentIndex(window.review_combo.findData("KEEP"))
        window.review_button.click()
        wait_for_catalog(lambda: not window._photo_busy)
        window.photo_grid.setCurrentRow(1)
        window.review_combo.setCurrentIndex(window.review_combo.findData("REJECT"))
        window.review_button.click()
        wait_for_catalog(lambda: not window._photo_busy)
        window.review_filter.setCurrentIndex(window.review_filter.findData("KEEP"))
        assert window.photo_grid.item(1).isHidden()
        window.export_session_button.click()
        wait_for_catalog(lambda: not window._photo_busy)
        assert "Export completato: 2/2 scatti, 2 sidecar" in window.import_status.text()
        records = _read_xmp(executable, source)
        assert {item["Rating"] for item in records} == {5, -1}
        assert {item["Label"] for item in records} == {"Green", "Red"}
        assert window.review_filter.currentData() == "KEEP"
    assert {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in source.glob("*.png")
    } == originals
