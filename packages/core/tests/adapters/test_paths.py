"""Test della directory dati applicazione per piattaforma (F1.D2.WP2)."""

from __future__ import annotations

import pytest

from shotkeepr.core.adapters import paths


def test_app_data_dir_linux_uses_xdg_data_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg-data")
    assert paths.app_data_dir() == paths.Path("/tmp/xdg-data/shotkeepr")


def test_app_data_dir_linux_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.app_data_dir() == paths.Path.home() / ".local" / "share" / "shotkeepr"


def test_app_data_dir_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    expected = paths.Path.home() / "Library" / "Application Support" / paths.APP_NAME
    assert paths.app_data_dir() == expected


def test_app_data_dir_windows_uses_appdata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", "C:\\Users\\tester\\AppData\\Roaming")
    expected = paths.Path("C:\\Users\\tester\\AppData\\Roaming") / paths.APP_NAME
    assert paths.app_data_dir() == expected


def test_app_data_dir_windows_falls_back_without_appdata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)
    expected = paths.Path.home() / "AppData" / "Roaming" / paths.APP_NAME
    assert paths.app_data_dir() == expected


def test_derived_paths_are_relative_to_app_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg-data")
    root = paths.app_data_dir()
    assert paths.db_path() == root / "shotkeepr.db"
    assert paths.runtime_dir() == root / "run"
    assert paths.log_dir() == root / "logs"
