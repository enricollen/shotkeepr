import time
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QApplication

from shotkeepr.desktop import connection as bridge
from shotkeepr.desktop import runtime as module
from shotkeepr.desktop.api_client.errors import UnexpectedStatus
from shotkeepr.desktop.api_client.models import HealthOut, SettingsOut, Theme
from shotkeepr.desktop.connection import CoreConnection
from shotkeepr.desktop.runtime import CoreRuntime


def test_real_core_theme_persists_after_restart(
    qt_app: QApplication, wait_until: Callable, tmp_path: Path
) -> None:
    runtime = CoreRuntime(data_dir=tmp_path)
    connection = CoreConnection()
    received: list[SettingsOut] = []
    failures: list[str] = []
    runtime.ready.connect(connection.connect_to)
    runtime.failed.connect(failures.append)
    connection.settings_received.connect(received.append)
    try:
        runtime.start()
        wait_until(lambda: bool(received) and connection._worker is None)
        assert received[-1].theme == "DARK"
        received.clear()
        connection.set_theme(Theme.LIGHT)
        wait_until(lambda: bool(received) and connection._worker is None)
        assert received[-1].theme == "LIGHT"
        assert not failures
    finally:
        connection.shutdown()
        runtime.stop()
    assert runtime._process.state() == QProcess.ProcessState.NotRunning
    assert runtime._directory is None

    second = CoreRuntime(data_dir=tmp_path)
    reconnected = CoreConnection()
    loaded: list[SettingsOut] = []
    second.ready.connect(reconnected.connect_to)
    reconnected.settings_received.connect(loaded.append)
    try:
        second.start()
        wait_until(lambda: bool(loaded) and reconnected._worker is None)
        assert loaded[-1].theme == "LIGHT"
    finally:
        reconnected.shutdown()
        second.stop()


def test_http_worker_keeps_qt_event_loop_responsive(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow_health(**kwargs: object) -> HealthOut:
        time.sleep(0.15)
        return HealthOut(status="ok")

    settings = SettingsOut(theme="DARK", catalog_enabled=False, edition="OPEN", log_level="INFO")
    monkeypatch.setattr(bridge, "health", slow_health)
    monkeypatch.setattr(bridge, "get_settings", lambda **kwargs: settings)
    connection = CoreConnection()
    ticks: list[bool] = []
    loaded: list[SettingsOut] = []
    connection.settings_received.connect(loaded.append)
    try:
        connection.connect_to("http://127.0.0.1:12345", "test")
        QTimer.singleShot(20, lambda: ticks.append(not loaded))
        wait_until(lambda: bool(loaded) and connection._worker is None)
        assert ticks == [True]
    finally:
        connection.shutdown()


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("not reachable"),
        UnexpectedStatus(401, b"secret response"),
        ValueError("invalid response"),
    ],
)
def test_errors_are_visible_without_exposing_credentials(
    qt_app: QApplication,
    wait_until: Callable,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    def fail(**kwargs: object) -> None:
        raise error

    monkeypatch.setattr(bridge, "health", fail)
    connection = CoreConnection()
    statuses: list[tuple[bool, str]] = []
    connection.status_changed.connect(lambda ok, message: statuses.append((ok, message)))
    try:
        connection.connect_to("http://127.0.0.1:12345", "test")
        wait_until(lambda: bool(statuses) and connection._worker is None)
        assert statuses[-1][0] is False
        assert "secret" not in statuses[-1][1]
    finally:
        connection.shutdown()


def test_missing_core_executable_is_reported(
    qt_app: QApplication, wait_until: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module.sys, "executable", "/nonexistent/shotkeepr-python")
    runtime = CoreRuntime()
    errors: list[str] = []
    runtime.failed.connect(errors.append)
    try:
        runtime.start()
        wait_until(lambda: bool(errors))
        assert "Impossibile avviare" in errors[0]
    finally:
        runtime.stop()
