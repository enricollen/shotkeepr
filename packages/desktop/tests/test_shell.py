from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QSplitter

from shotkeepr.desktop.api_client.models import SettingsOut, Theme
from shotkeepr.desktop.connection import CoreConnection
from shotkeepr.desktop.window import MainWindow


@pytest.fixture
def shell(qt_app: QApplication) -> Iterator[MainWindow]:
    connection = CoreConnection()
    window = MainWindow(qt_app, connection)
    window.show()
    qt_app.processEvents()
    yield window
    connection.shutdown()
    window.close()


def test_layout_fits_minimum_display(shell: MainWindow) -> None:
    splitter = shell.centralWidget()
    assert isinstance(splitter, QSplitter)
    assert splitter.count() == 3
    assert shell.width() <= 1366
    assert shell.height() <= 768
    assert shell.minimumWidth() <= 1366
    assert shell.minimumHeight() <= 768
    assert shell.detail_tabs.count() == 3
    assert shell.photo_grid.count() == 0
    assert shell.photo_stack.currentWidget() == shell.empty_state
    assert "non e' ancora disponibile" in shell.empty_state.text()
    assert shell.folder_model.isReadOnly()


def test_folder_selection_without_modifying_originals(shell: MainWindow, tmp_path: Path) -> None:
    original = tmp_path / "sample.jpg"
    original.write_bytes(b"unchanged")
    selected: list[str] = []
    shell.folder_selected.connect(selected.append)
    shell.select_folder(str(tmp_path))
    assert selected == [str(tmp_path)]
    assert shell.source_label.text() == str(tmp_path)
    assert original.read_bytes() == b"unchanged"
    shell.select_folder(str(tmp_path / "missing"))
    assert len(selected) == 1
    assert "non e' disponibile" in shell.statusBar().currentMessage()


def test_open_keyboard_shortcut(
    shell: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))
    QTest.keyClick(shell, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    assert shell.source_label.text() == str(tmp_path)


@pytest.mark.parametrize("theme", [Theme.LIGHT, Theme.DARK])
def test_theme_from_core_is_neutral(shell: MainWindow, qt_app: QApplication, theme: Theme) -> None:
    settings = SettingsOut(
        theme=theme.value, catalog_enabled=False, edition="OPEN", log_level="INFO"
    )
    shell._connection.settings_received.emit(settings)
    assert shell.theme_actions[theme].isChecked()
    palette = qt_app.palette()
    for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.Text):
        color = palette.color(role)
        assert color.red() == color.green() == color.blue()
    assert (
        palette.color(QPalette.ColorRole.Base).lightness() > 128
        if theme == Theme.LIGHT
        else (palette.color(QPalette.ColorRole.Base).lightness() < 128)
    )


def test_theme_waits_for_saved_response(shell: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[Theme] = []
    monkeypatch.setattr(shell._connection, "set_theme", requested.append)
    assert not shell.theme_actions[Theme.LIGHT].isEnabled()
    shell.set_connection_status(True, "Nucleo connesso")
    shell.theme_actions[Theme.LIGHT].trigger()
    assert requested == [Theme.LIGHT]
    assert shell.theme_actions[Theme.DARK].isChecked()
    shell.set_connection_status(False, "Token non valido")
    assert not shell.theme_actions[Theme.LIGHT].isEnabled()


def test_tree_keyboard_navigation(shell: MainWindow, wait_until: Callable) -> None:
    shell.folder_tree.setFocus()
    wait_until(shell.folder_tree.hasFocus)
    QTest.keyClick(shell.folder_tree, Qt.Key.Key_Down)
    QTest.keyClick(shell.folder_tree, Qt.Key.Key_Return)
    assert shell.folder_tree.hasFocus()
