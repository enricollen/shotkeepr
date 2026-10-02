"""Desktop shell: source tree, photo grid and read-only detail panels."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFileSystemModel,
    QLabel,
    QListView,
    QListWidget,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from shotkeepr.desktop.api_client.models import SettingsOut, Theme
from shotkeepr.desktop.connection import CoreConnection
from shotkeepr.desktop.themes import apply_theme


class MainWindow(QMainWindow):
    closing = Signal()
    folder_selected = Signal(str)

    def __init__(self, app: QApplication, connection: CoreConnection) -> None:
        super().__init__()
        self._app = app
        self._connection = connection
        self._connected = False
        self._busy = False
        self._theme = Theme.DARK
        self.setWindowTitle("ShotKeepr")
        self.setMinimumSize(1100, 640)
        self.resize(1280, 720)
        self._build_actions()
        self._build_layout()
        self._status = QLabel("Avvio del nucleo...")
        self.statusBar().addWidget(self._status, 1)
        connection.settings_received.connect(self._settings_received)
        connection.status_changed.connect(self.set_connection_status)
        connection.busy_changed.connect(self._set_busy)
        apply_theme(app, self._theme)

    def _build_actions(self) -> None:
        files = self.menuBar().addMenu("&File")
        self.open_action = QAction("&Apri cartella...", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self._choose_folder)
        files.addAction(self.open_action)
        quit_action = QAction("&Esci", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        files.addAction(quit_action)

        settings = self.menuBar().addMenu("&Impostazioni")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self.theme_actions: dict[Theme, QAction] = {}
        for theme, label in ((Theme.DARK, "Tema &scuro"), (Theme.LIGHT, "Tema &chiaro")):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(theme == self._theme)
            action.setEnabled(False)
            action.triggered.connect(
                lambda _checked=False, selected=theme: self._choose_theme(selected)
            )
            self._theme_group.addAction(action)
            settings.addAction(action)
            self.theme_actions[theme] = action

        self.retry_action = QAction("&Riconnetti al nucleo", self)
        self.retry_action.setShortcut(QKeySequence("Ctrl+R"))
        self.retry_action.triggered.connect(self._connection.refresh)
        settings.addAction(self.retry_action)
        toolbar = QToolBar("Navigazione", self)
        toolbar.setObjectName("navigation")
        toolbar.setMovable(False)
        toolbar.addAction(self.open_action)
        self.addToolBar(toolbar)

    def _build_layout(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.folder_model = QFileSystemModel(self)
        self.folder_model.setReadOnly(True)
        self.folder_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot)
        self.folder_model.setRootPath(str(Path.home()))
        self.folder_tree = QTreeView()
        self.folder_tree.setAccessibleName("Cartelle sorgente")
        self.folder_tree.setModel(self.folder_model)
        self.folder_tree.setRootIndex(self.folder_model.index(str(Path.home())))
        self.folder_tree.setHeaderHidden(True)
        for column in range(1, self.folder_model.columnCount()):
            self.folder_tree.hideColumn(column)
        self.folder_tree.clicked.connect(self._tree_selected)
        self.folder_tree.activated.connect(self._tree_selected)
        splitter.addWidget(self.folder_tree)

        center = QWidget()
        layout = QVBoxLayout(center)
        self.source_label = QLabel("Nessuna cartella selezionata")
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)
        self.photo_grid = QListWidget()
        self.photo_grid.setAccessibleName("Griglia degli scatti")
        self.photo_grid.setViewMode(QListView.ViewMode.IconMode)
        self.photo_grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.photo_grid.setGridSize(QSize(180, 180))
        self.photo_grid.setIconSize(QSize(160, 140))
        self.photo_grid.setMovement(QListView.Movement.Static)
        self.empty_state = QLabel(
            "Apri una cartella per iniziare.\nL'analisi degli scatti non e' ancora disponibile."
        )
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setWordWrap(True)
        self.photo_stack = QStackedWidget()
        self.photo_stack.addWidget(self.empty_state)
        self.photo_stack.addWidget(self.photo_grid)
        layout.addWidget(self.photo_stack, 1)
        splitter.addWidget(center)

        self.detail_tabs = QTabWidget()
        self.detail_tabs.setAccessibleName("Pannelli di dettaglio")
        for title, text in (
            ("Dettagli", "Seleziona uno scatto per visualizzare i dettagli."),
            ("Criteri", "I criteri di selezione saranno disponibili con l'analisi."),
        ):
            label = QLabel(text)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignTop)
            label.setMargin(12)
            self.detail_tabs.addTab(label, title)
        splitter.addWidget(self.detail_tabs)
        splitter.setSizes([240, 700, 260])
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        QWidget.setTabOrder(self.folder_tree, self.photo_grid)
        QWidget.setTabOrder(self.photo_grid, self.detail_tabs)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Apri cartella di scatti", str(Path.home()))
        if folder:
            self.select_folder(folder)

    def _tree_selected(self, index: QModelIndex) -> None:
        self.select_folder(self.folder_model.filePath(index))

    def select_folder(self, folder: str) -> None:
        path = Path(folder)
        if not path.is_dir():
            self.statusBar().showMessage("La cartella non e' disponibile.", 5000)
            return
        self.source_label.setText(str(path))
        self.folder_tree.setCurrentIndex(self.folder_model.index(str(path)))
        self.folder_tree.scrollTo(self.folder_tree.currentIndex())
        self.folder_selected.emit(str(path))

    def _choose_theme(self, theme: Theme) -> None:
        # Only apply the returned setting, so failed writes never look persisted.
        self.theme_actions[self._theme].setChecked(True)
        self._connection.set_theme(theme)

    def _settings_received(self, settings: SettingsOut) -> None:
        self._theme = Theme(settings.theme)
        self.theme_actions[self._theme].setChecked(True)
        apply_theme(self._app, self._theme)

    def set_connection_status(self, connected: bool, message: str) -> None:
        self._connected = connected
        self._status.setText(message)
        self._status.setToolTip(message)
        self._enable_actions()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._enable_actions()

    def _enable_actions(self) -> None:
        for action in self.theme_actions.values():
            action.setEnabled(self._connected and not self._busy)
        self.retry_action.setEnabled(not self._busy)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.closing.emit()
        super().closeEvent(event)
