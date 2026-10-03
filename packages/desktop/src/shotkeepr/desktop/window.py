"""Desktop shell: saved sessions, burst navigation, photo details and manual review."""

from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFileSystemModel,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from shotkeepr.desktop.api_client.models import (
    BurstGroupingOut,
    ExposureOut,
    ImportJobOut,
    ImportJobStatus,
    ReviewOut,
    ReviewStatus,
    SessionStatus,
    SettingsOut,
    SharpnessOut,
    ShotOut,
    Theme,
    XmpOut,
)
from shotkeepr.desktop.connection import CoreConnection
from shotkeepr.desktop.photos import (
    PhotoController,
    PhotoPage,
    PhotoSessions,
    PreviewBatch,
    XmpBatch,
)
from shotkeepr.desktop.themes import apply_theme

REVIEW_LABELS = {
    ReviewStatus.KEEP: "Tenuta",
    ReviewStatus.REJECT: "Scartata",
    ReviewStatus.REVIEW: "Da rivedere",
}


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
        self._import_active = False
        self._photo_busy = False
        self._has_more = False
        self.photos = PhotoController(self)
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
        connection.endpoint_changed.connect(self.photos.configure)
        self.photos.job_updated.connect(self._job_updated)
        self.photos.page_received.connect(self._page_received)
        self.photos.sessions_received.connect(self._sessions_received)
        self.photos.exposure_received.connect(self._measurement_received)
        self.photos.sharpness_received.connect(self._measurement_received)
        self.photos.review_received.connect(self._review_received)
        self.photos.xmp_received.connect(self._xmp_received)
        self.photos.groups_received.connect(self._groups_received)
        self.photos.measurement_progress.connect(self._measurement_progress)
        self.photos.measurements_finished.connect(self._measurements_finished)
        self.photos.xmp_progress.connect(self._xmp_progress)
        self.photos.xmp_session_finished.connect(self._xmp_session_finished)
        self.photos.failed.connect(self._photo_error)
        self.photos.active_changed.connect(self._set_import_active)
        self.photos.busy_changed.connect(self._set_photo_busy)
        self.closing.connect(self.photos.shutdown)
        apply_theme(app, self._theme)
        self._enable_actions()

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
        self._build_folder_tree()
        splitter.addWidget(self.folder_tree)
        center = QWidget()
        layout = QVBoxLayout(center)
        self._build_session_controls(layout)
        self._build_import_controls(layout)
        self._build_photo_grid(layout)
        splitter.addWidget(center)
        self._build_details()
        splitter.addWidget(self.detail_tabs)
        splitter.setSizes([240, 700, 260])
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        QWidget.setTabOrder(self.folder_tree, self.photo_grid)
        QWidget.setTabOrder(self.photo_grid, self.detail_tabs)

    def _build_folder_tree(self) -> None:
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

    def _build_session_controls(self, layout: QVBoxLayout) -> None:
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Sessioni salvate:"))
        self.session_combo = QComboBox()
        self.session_combo.setAccessibleName("Sessioni salvate nel nucleo")
        self.session_combo.setPlaceholderText("Nessuna sessione salvata")
        self.session_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.session_combo.currentIndexChanged.connect(lambda _index: self._enable_actions())
        controls.addWidget(self.session_combo, 1)
        self.open_session_button = QPushButton("Apri sessione")
        self.open_session_button.clicked.connect(self._open_session)
        controls.addWidget(self.open_session_button)
        self.refresh_sessions_button = QPushButton("Aggiorna sessioni")
        self.refresh_sessions_button.clicked.connect(self.photos.refresh_sessions)
        controls.addWidget(self.refresh_sessions_button)
        layout.addLayout(controls)

    def _build_import_controls(self, layout: QVBoxLayout) -> None:
        self.source_label = QLabel("Nessuna cartella selezionata")
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)
        self.source_edit = QLineEdit()
        self.source_edit.setAccessibleName("Percorso della cartella nel nucleo")
        self.source_edit.setPlaceholderText("Percorso nel nucleo; in Docker usare /photos")
        self.source_edit.textChanged.connect(lambda _text: self._enable_actions())
        layout.addWidget(self.source_edit)
        controls = QHBoxLayout()
        self.recursive_check = QCheckBox("Sottocartelle")
        self.recursive_check.setChecked(True)
        self.import_button = QPushButton("Importa")
        self.import_button.clicked.connect(self._start_import)
        self.cancel_button = QPushButton("Annulla")
        self.cancel_button.clicked.connect(self.photos.cancel_import)
        self.import_retry_button = QPushButton("Riprova stato")
        self.import_retry_button.clicked.connect(self.photos.refresh_job)
        for widget in (
            self.recursive_check,
            self.import_button,
            self.cancel_button,
            self.import_retry_button,
        ):
            controls.addWidget(widget)
        layout.addLayout(controls)
        self.import_status = QLabel("Nessuna importazione avviata")
        self.import_status.setWordWrap(True)
        layout.addWidget(self.import_status)
        self.import_progress = QProgressBar()
        self.import_progress.setRange(0, 1)
        self.import_progress.setValue(0)
        layout.addWidget(self.import_progress)

    def _build_measurement_controls(self, layout: QVBoxLayout) -> None:
        controls = QHBoxLayout()
        self.measure_session_button = QPushButton("Misura anteprime della sessione")
        self.measure_session_button.setToolTip(
            "Esposizione e nitidezza di tutti gli scatti, anche fuori dai filtri e dalle pagine "
            "caricate. Non analisi AI o selezione automatica."
        )
        self.measure_session_button.clicked.connect(self._measure_session)
        self.cancel_measurements_button = QPushButton("Ferma misure")
        self.cancel_measurements_button.setToolTip(
            "Arresta dopo la richiesta in corso; conserva le misure gia' salvate."
        )
        self.cancel_measurements_button.clicked.connect(self._cancel_measurements)
        controls.addWidget(self.measure_session_button)
        controls.addWidget(self.cancel_measurements_button)
        layout.addLayout(controls)

    def _build_session_export_controls(self, layout: QVBoxLayout) -> None:
        controls = QHBoxLayout()
        self.export_session_button = QPushButton("Esporta XMP della sessione...")
        self.export_session_button.setToolTip(
            "Scrive gli stati salvati di tutti gli scatti, anche non caricati o nascosti "
            "dai filtri, dopo conferma esplicita."
        )
        self.export_session_button.clicked.connect(self._export_session)
        self.cancel_export_button = QPushButton("Ferma export")
        self.cancel_export_button.setToolTip(
            "Arresta dopo la richiesta in corso; non annulla i sidecar gia' scritti."
        )
        self.cancel_export_button.clicked.connect(self._cancel_session_export)
        controls.addWidget(self.export_session_button)
        controls.addWidget(self.cancel_export_button)
        layout.addLayout(controls)

    def _build_photo_grid(self, layout: QVBoxLayout) -> None:
        self._build_measurement_controls(layout)
        self._build_session_export_controls(layout)
        self._build_group_controls(layout)
        self.review_filter = QComboBox()
        self.review_filter.setAccessibleName("Filtra lo stato degli scatti caricati")
        self.review_filter.addItem("Tutti gli scatti caricati", "")
        for status, label in REVIEW_LABELS.items():
            self.review_filter.addItem(label, status.value)
        self.review_filter.setToolTip(
            "Il filtro riguarda le pagine gia' caricate, non tutta la sessione."
        )
        layout.addWidget(self.review_filter)
        self.photo_grid = QListWidget()
        self.photo_grid.setAccessibleName("Griglia degli scatti")
        self.photo_grid.setViewMode(QListView.ViewMode.IconMode)
        self.photo_grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.photo_grid.setGridSize(QSize(180, 220))
        self.photo_grid.setIconSize(QSize(160, 140))
        self.photo_grid.setMovement(QListView.Movement.Static)
        self.photo_grid.currentItemChanged.connect(self._show_details)
        self.review_filter.currentIndexChanged.connect(lambda _index: self._filter_reviews())
        self.empty_state = QLabel(
            "Apri una cartella e premi Importa, oppure apri una sessione salvata.\n"
            "La valutazione degli scatti non e' ancora disponibile."
        )
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setWordWrap(True)
        self.photo_stack = QStackedWidget()
        self.photo_stack.addWidget(self.empty_state)
        self.photo_stack.addWidget(self.photo_grid)
        layout.addWidget(self.photo_stack, 1)
        self.load_more_button = QPushButton("Carica altri scatti")
        self.load_more_button.clicked.connect(self.photos.load_more)
        self.load_more_button.setEnabled(False)
        layout.addWidget(self.load_more_button)

    def _build_group_controls(self, layout: QVBoxLayout) -> None:
        controls = QHBoxLayout()
        self.burst_gap = QDoubleSpinBox()
        self.burst_gap.setAccessibleName("Intervallo massimo tra scatti della stessa fotocamera")
        self.burst_gap.setRange(0.01, 60)
        self.burst_gap.setDecimals(2)
        self.burst_gap.setSingleStep(0.1)
        self.burst_gap.setValue(2)
        self.burst_gap.setSuffix(" s")
        controls.addWidget(QLabel("Intervallo raffica:"))
        controls.addWidget(self.burst_gap)
        self.group_button = QPushButton("Raggruppa raffiche")
        self.group_button.setToolTip(
            "Usa ora EXIF, modello e seriale fotocamera; non similarita' visiva o punteggi AI."
        )
        self.group_button.clicked.connect(self._group_bursts)
        controls.addWidget(self.group_button)
        controls.addStretch()
        layout.addLayout(controls)
        self.group_filter = QComboBox()
        self.group_filter.setAccessibleName("Gruppi della sessione completa")
        self.group_filter.addItem("Tutti gli scatti della sessione", "")
        self.group_filter.setToolTip("Il gruppo viene filtrato nel nucleo, su tutta la sessione.")
        self.group_filter.currentIndexChanged.connect(self._choose_group)
        layout.addWidget(self.group_filter)

    def _build_details(self) -> None:
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
            if title == "Dettagli":
                self.details_label = label
                panel = QWidget()
                layout = QVBoxLayout(panel)
                self.details_scroll = QScrollArea()
                self.details_scroll.setWidgetResizable(True)
                self.details_scroll.setWidget(label)
                layout.addWidget(self.details_scroll, 1)
                self.exposure_button = QPushButton("Misura esposizione (anteprima)")
                self.exposure_button.setToolTip(
                    "Indicatori sul JPEG in cache, non una valutazione AI o della gamma RAW."
                )
                self.exposure_button.clicked.connect(self._measure_exposure)
                layout.addWidget(self.exposure_button)
                self.sharpness_button = QPushButton("Misura nitidezza (anteprima)")
                self.sharpness_button.setToolTip(
                    "Dettaglio globale del JPEG in cache, non fuoco del soggetto o valutazione AI."
                )
                self.sharpness_button.clicked.connect(self._measure_sharpness)
                layout.addWidget(self.sharpness_button)
                self.review_combo = QComboBox()
                self.review_combo.setAccessibleName("Decisione manuale sullo scatto")
                for status, decision_label in REVIEW_LABELS.items():
                    self.review_combo.addItem(decision_label, status.value)
                layout.addWidget(self.review_combo)
                self.review_button = QPushButton("Salva decisione manuale")
                self.review_button.clicked.connect(self._save_review)
                layout.addWidget(self.review_button)
                self.xmp_button = QPushButton("Esporta XMP dello scatto...")
                self.xmp_button.clicked.connect(self._export_xmp)
                self.xmp_button.setToolTip(
                    "Scrive/aggiorna i sidecar nel filesystem del nucleo, dopo conferma."
                )
                layout.addWidget(self.xmp_button)
                self.detail_tabs.addTab(panel, title)
            else:
                self.detail_tabs.addTab(label, title)
        self.exclusions = QListWidget()
        self.detail_tabs.addTab(self.exclusions, "Esclusi")

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
        self.source_edit.setText(str(path))
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
        newly_connected = connected and not self._connected
        self._connected = connected
        self._status.setText(message)
        self._status.setToolTip(message)
        self._enable_actions()
        if newly_connected:
            self.photos.refresh_sessions()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._enable_actions()

    def _enable_actions(self) -> None:
        for action in self.theme_actions.values():
            action.setEnabled(self._connected and not self._busy)
        self.retry_action.setEnabled(not self._busy)
        if hasattr(self, "import_button"):
            self.import_button.setEnabled(
                self._connected
                and bool(self.source_edit.text().strip())
                and not self._import_active
                and not self._photo_busy
            )
            self.cancel_button.setEnabled(self._import_active)
            self.import_retry_button.setEnabled(self._import_active and not self._photo_busy)
            self.open_action.setEnabled(not self._import_active)
            self.folder_tree.setEnabled(not self._import_active)
            self.source_edit.setEnabled(not self._import_active)
            self.recursive_check.setEnabled(not self._import_active)
            self.load_more_button.setEnabled(self._has_more and not self._photo_busy)
            browse_enabled = self._connected and not self._import_active and not self._photo_busy
            self.session_combo.setEnabled(browse_enabled)
            self.refresh_sessions_button.setEnabled(browse_enabled)
            self.open_session_button.setEnabled(
                browse_enabled and isinstance(self.session_combo.currentData(), str)
            )
            self.exposure_button.setEnabled(browse_enabled and self._selected_shot() is not None)
            self.sharpness_button.setEnabled(browse_enabled and self._selected_shot() is not None)
            self.review_combo.setEnabled(browse_enabled and self._selected_shot() is not None)
            self.review_button.setEnabled(browse_enabled and self._selected_shot() is not None)
            self.xmp_button.setEnabled(browse_enabled and self._selected_shot() is not None)
            self.measure_session_button.setEnabled(
                browse_enabled and self.photos.session_id is not None
            )
            self.cancel_measurements_button.setEnabled(
                self.photos.measuring_session and not self.photos.measurement_cancel_requested
            )
            self.export_session_button.setEnabled(
                browse_enabled and self.photos.session_id is not None
            )
            self.cancel_export_button.setEnabled(
                self.photos.exporting_session and not self.photos.export_cancel_requested
            )
            self.group_button.setEnabled(browse_enabled and self.photos.session_id is not None)
            self.burst_gap.setEnabled(browse_enabled and self.photos.session_id is not None)
            self.group_filter.setEnabled(browse_enabled and self.photos.session_id is not None)

    def _sessions_received(self, result: PhotoSessions) -> None:
        current_id = self.photos.session_id
        selected = str(current_id) if current_id is not None else self.session_combo.currentData()
        self.session_combo.clear()
        for session in result.items:
            self.session_combo.addItem(
                f"{session.started_at.astimezone():%d/%m/%Y %H:%M:%S} | "
                f"{session.source_folder} | {session.status.value} | {session.shots} scatti",
                str(session.session_id),
            )
        index = self.session_combo.findData(selected)
        self.session_combo.setCurrentIndex(index if index >= 0 else 0)
        self._enable_actions()

    def _open_session(self) -> None:
        selected = self.session_combo.currentData()
        if not isinstance(selected, str):
            self._photo_error("Selezionare una sessione salvata.")
            return
        try:
            session_id = uuid.UUID(selected)
        except ValueError:
            self._photo_error("Identificativo della sessione non valido.")
            return
        self.import_status.setText("Caricamento della sessione salvata...")
        self.photos.open_session(session_id)

    def _start_import(self) -> None:
        folder = self.source_edit.text().strip()
        if not folder:
            self._photo_error("Specificare una cartella nel nucleo.")
            return
        previous = self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem("Tutti gli scatti della sessione", "")
        self.group_filter.blockSignals(previous)
        self.burst_gap.setValue(2)
        self.photo_grid.clear()
        self.exclusions.clear()
        self._has_more = False
        self.photo_stack.setCurrentWidget(self.empty_state)
        self.import_status.setText("Avvio dell'importazione...")
        self.photos.start_import(folder, self.recursive_check.isChecked())

    def _set_import_active(self, active: bool) -> None:
        self._import_active = active
        self.import_progress.setRange(0, 0 if active else 1)
        self._enable_actions()

    def _set_photo_busy(self, busy: bool) -> None:
        self._photo_busy = busy
        if busy and self.photos.measuring_session:
            self.import_status.setText("Misure delle anteprime della sessione in corso...")
            self.import_progress.setRange(0, 0)
        elif busy and self.photos.exporting_session:
            self.import_status.setText("Export XMP dell'intera sessione in corso...")
            self.import_progress.setRange(0, 0)
        self._enable_actions()

    def _job_updated(self, job: ImportJobOut) -> None:
        self.source_label.setText(job.source_folder)
        if job.status in {ImportJobStatus.QUEUED, ImportJobStatus.RUNNING}:
            prefix = "Annullamento richiesto" if job.cancel_requested else "Importazione"
            self.import_status.setText(
                f"{prefix}: {job.processed} file, {job.imported_files} importati, "
                f"{job.excluded_files} esclusi"
            )
        elif job.status is ImportJobStatus.SUCCEEDED:
            self.import_status.setText(
                f"Importati {job.shots} scatti; {job.excluded_files} file esclusi. "
                "Qualita' non ancora valutata."
            )
            self.import_progress.setRange(0, 1)
            self.import_progress.setValue(1)
        elif job.status is ImportJobStatus.CANCELLED:
            self.import_status.setText(
                "Importazione annullata; nessuno scatto parziale pubblicato."
            )
        if job.status in {ImportJobStatus.SUCCEEDED, ImportJobStatus.CANCELLED}:
            self.photos.refresh_sessions()

    def _photo_error(self, message: str) -> None:
        if (
            self.photos.measuring_session or self.photos.exporting_session
        ) and self.import_progress.maximum() == 0:
            self.import_progress.setRange(0, 1)
        self._restore_group_filter()
        self.import_status.setText(message)
        self.statusBar().showMessage(message, 10000)

    def _page_received(self, result: PhotoPage) -> None:
        if result.page.offset == 0:
            self._group_options(result)
            self.photo_grid.clear()
            self.source_label.setText(result.session.source_folder)
            self.source_edit.setText(result.session.source_folder)
            self.recursive_check.setChecked(result.session.include_subfolders)
            index = self.session_combo.findData(str(result.session.session_id))
            if index >= 0:
                self.session_combo.setCurrentIndex(index)
            self.import_status.setText(
                f"Sessione {result.session.status.value}: {result.session.shots} scatti; "
                f"{result.page.total} nella vista corrente; "
                f"{len(result.session.excluded)} file esclusi."
            )
            self.import_progress.setRange(0, 1)
            self.import_progress.setValue(
                int(result.session.status in {SessionStatus.IMPORTED, SessionStatus.ANALYZED})
            )
        for thumbnail in result.thumbnails:
            shot = thumbnail.shot
            name = Path(shot.files[0].path).name if shot.files else str(shot.shot_id)
            label = f"{name}\nRAW+JPEG" if shot.is_raw_pair else name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, shot)
            if thumbnail.content is not None:
                pixmap = QPixmap()
                if pixmap.loadFromData(thumbnail.content):
                    item.setIcon(
                        QIcon(
                            pixmap.scaled(
                                self.photo_grid.iconSize(),
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
                    )
                else:
                    item.setToolTip("Anteprima non decodificabile")
                    item.setText(f"{label}\nAnteprima non disponibile")
            else:
                item.setToolTip(thumbnail.error or "Anteprima non disponibile")
                item.setText(f"{label}\nAnteprima assente")
            item.setData(Qt.ItemDataRole.UserRole + 1, item.text())
            self._label_review(item, shot)
            self.photo_grid.addItem(item)
        self._has_more = result.page.offset + len(result.page.items) < result.page.total
        self.photo_stack.setCurrentWidget(
            self.photo_grid if self.photo_grid.count() else self.empty_state
        )
        self.exclusions.clear()
        for excluded in result.session.excluded[:200]:
            self.exclusions.addItem(
                f"{Path(excluded.path).name}: {excluded.reason.value}\n{excluded.detail}"
            )
        if len(result.session.excluded) > 200:
            self.exclusions.addItem(
                f"Altri {len(result.session.excluded) - 200} file esclusi nel catalogo."
            )
        if self.photo_grid.currentRow() < 0 and self.photo_grid.count():
            self.photo_grid.setCurrentRow(0)
        self._filter_reviews()
        self._enable_actions()

    def _selected_shot(self) -> ShotOut | None:
        current = self.photo_grid.currentItem()
        if current is None or current.isHidden():
            return None
        shot = current.data(Qt.ItemDataRole.UserRole)
        return shot if isinstance(shot, ShotOut) else None

    @staticmethod
    def _review_status(shot: ShotOut) -> ReviewStatus:
        return shot.review.status if isinstance(shot.review, ReviewOut) else ReviewStatus.REVIEW

    def _group_bursts(self) -> None:
        self.import_status.setText("Raggruppamento delle raffiche temporali in corso...")
        self.photos.group_bursts(self.burst_gap.value())

    def _groups_received(self, result: BurstGroupingOut) -> None:
        self.import_status.setText(
            f"Salvate {len(result.groups)} raffiche; "
            f"{result.ungrouped_shots} scatti senza raffica. "
            "Ricaricamento della sessione..."
        )

    def _choose_group(self, _index: int) -> None:
        session_id = self.photos.session_id
        if session_id is None:
            self._photo_error("Aprire una sessione prima di scegliere il gruppo.")
            return
        selected = self.group_filter.currentData()
        try:
            group_id = (
                uuid.UUID(selected)
                if isinstance(selected, str) and selected not in {"", "ungrouped"}
                else None
            )
        except ValueError:
            self._photo_error("Identificativo del gruppo non valido.")
            return
        self.import_status.setText("Caricamento del gruppo dal catalogo...")
        self.photos.open_session(session_id, group_id=group_id, ungrouped=selected == "ungrouped")

    def _restore_group_filter(self) -> None:
        selected = (
            "ungrouped"
            if self.photos.view_ungrouped
            else str(self.photos.view_group_id)
            if self.photos.view_group_id is not None
            else ""
        )
        previous = self.group_filter.blockSignals(True)
        self.group_filter.setCurrentIndex(self.group_filter.findData(selected))
        self.group_filter.blockSignals(previous)

    def _group_options(self, result: PhotoPage) -> None:
        previous = self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem("Tutti gli scatti della sessione", "")
        grouping = result.session.grouping
        if isinstance(grouping, BurstGroupingOut):
            self.group_filter.addItem(
                f"Senza raffica ({grouping.ungrouped_shots} scatti)", "ungrouped"
            )
            for index, group in enumerate(grouping.groups, start=1):
                self.group_filter.addItem(
                    f"Raffica {index} | {group.shots} scatti | {group.camera_model} | "
                    f"{group.first_capture.astimezone():%H:%M:%S}",
                    str(group.group_id),
                )
        self.burst_gap.setValue(
            grouping.gap_seconds
            if isinstance(grouping, BurstGroupingOut) and grouping.gap_seconds is not None
            else 2
        )
        self.group_filter.blockSignals(previous)
        self._restore_group_filter()

    def _label_review(self, item: QListWidgetItem, shot: ShotOut) -> None:
        base = item.data(Qt.ItemDataRole.UserRole + 1)
        group = (
            f"Raffica {str(shot.group_id)[:8]}"
            if isinstance(shot.group_id, uuid.UUID)
            else "Senza raffica"
        )
        item.setText(f"{base}\n{REVIEW_LABELS[self._review_status(shot)]}\n{group}")

    def _filter_reviews(self) -> None:
        selected = self.review_filter.currentData()
        first_visible: QListWidgetItem | None = None
        for index in range(self.photo_grid.count()):
            item = self.photo_grid.item(index)
            shot = item.data(Qt.ItemDataRole.UserRole)
            hidden = (
                isinstance(shot, ShotOut)
                and bool(selected)
                and self._review_status(shot).value != selected
            )
            item.setHidden(hidden)
            if not hidden and first_visible is None:
                first_visible = item
        current = self.photo_grid.currentItem()
        if current is None or current.isHidden():
            if first_visible is None:
                self.photo_grid.setCurrentRow(-1)
            else:
                self.photo_grid.setCurrentItem(first_visible)
        self._show_details(self.photo_grid.currentItem(), None)

    def _save_review(self) -> None:
        shot = self._selected_shot()
        if shot is None:
            self._photo_error("Selezionare uno scatto per salvarne la revisione.")
            return
        status = ReviewStatus(self.review_combo.currentData())
        self.photos.set_review(shot.shot_id, status)

    def _review_received(self, review: ReviewOut) -> None:
        for index in range(self.photo_grid.count()):
            item = self.photo_grid.item(index)
            shot = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(shot, ShotOut) and shot.shot_id == review.shot_id:
                shot.review = review
                item.setData(Qt.ItemDataRole.UserRole, shot)
                self._label_review(item, shot)
                break
        self._filter_reviews()

    def _export_xmp(self) -> None:
        shot = self._selected_shot()
        if shot is None:
            self._photo_error("Selezionare uno scatto per esportare il sidecar.")
            return
        status = self._review_status(shot)
        confirmed = QMessageBox.question(
            self,
            "Conferma export XMP",
            f"Esportare lo stato salvato '{REVIEW_LABELS[status]}' per questo scatto?\n"
            "I sidecar saranno scritti accanto agli originali nel filesystem del nucleo.\n"
            "Rating ed etichetta colore esistenti saranno aggiornati; gli altri campi conservati.\n"
            "Le foto non saranno modificate o eliminate.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmed == QMessageBox.StandardButton.Yes:
            self.import_status.setText("Export XMP dello scatto in corso...")
            self.photos.export_xmp(shot.shot_id, status)

    def _export_session(self) -> None:
        confirmed = QMessageBox.question(
            self,
            "Conferma export XMP della sessione",
            "Esportare gli stati salvati di TUTTI gli scatti della sessione aperta?\n"
            "Sono inclusi Tenuta, Scartata e Da rivedere, anche fuori dai filtri e dalle pagine "
            "caricate. Modifiche non salvate nel pannello Dettagli non saranno esportate.\n"
            "I sidecar saranno scritti accanto agli originali nel filesystem del nucleo.\n"
            "Rating ed etichetta colore esistenti saranno aggiornati; gli altri campi conservati.\n"
            "Le foto non saranno modificate o eliminate. Arresti o errori non annullano "
            "i sidecar gia' scritti.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmed == QMessageBox.StandardButton.Yes:
            self.photos.export_session()

    def _cancel_session_export(self) -> None:
        self.photos.cancel_session_export()
        self.import_status.setText("Arresto dell'export dopo la richiesta in corso...")
        self._enable_actions()

    def _xmp_progress(self, completed: int, total: int) -> None:
        self.import_progress.setRange(0, max(1, total))
        self.import_progress.setValue(completed)
        prefix = "Arresto richiesto" if self.photos.export_cancel_requested else "Export XMP"
        self.import_status.setText(f"{prefix}: {completed}/{total} scatti confermati.")

    def _xmp_session_finished(self, result: XmpBatch) -> None:
        self.import_progress.setRange(0, max(1, result.total))
        self.import_progress.setValue(result.completed if result.total else 1)
        prefix = "Export annullato" if result.cancelled else "Export completato"
        message = (
            f"{prefix}: {result.completed}/{result.total} scatti, {result.paths} sidecar. "
            "Gli XMP gia' scritti restano nel nucleo; nessuna foto modificata."
        )
        self.import_status.setText(message)
        self.statusBar().showMessage(message, 10000)

    def _xmp_received(self, result: XmpOut) -> None:
        message = f"XMP esportato ({REVIEW_LABELS[result.status]}): {', '.join(result.paths)}"
        self.import_status.setText(message)
        self.statusBar().showMessage(message, 10000)

    def _measure_session(self) -> None:
        self.photos.measure_session()

    def _cancel_measurements(self) -> None:
        self.photos.cancel_measurements()
        self.import_status.setText("Arresto delle misure dopo la richiesta in corso...")
        self._enable_actions()

    def _measurement_progress(self, completed: int, total: int) -> None:
        self.import_progress.setRange(0, max(1, total))
        self.import_progress.setValue(completed)
        prefix = (
            "Arresto richiesto" if self.photos.measurement_cancel_requested else "Misure anteprime"
        )
        self.import_status.setText(f"{prefix}: {completed}/{total} scatti completati.")

    def _measurements_finished(self, result: PreviewBatch) -> None:
        self.import_progress.setRange(0, max(1, result.total))
        self.import_progress.setValue(result.completed if result.total else 1)
        prefix = "Misure annullate" if result.cancelled else "Misure completate"
        self.import_status.setText(
            f"{prefix}: {result.completed}/{result.total} scatti. "
            "Misure salvate conservate; nessuna selezione AI eseguita."
        )

    def _measure_exposure(self) -> None:
        shot = self._selected_shot()
        if shot is None:
            self._photo_error("Selezionare uno scatto per misurare l'esposizione.")
            return
        self.photos.measure_exposure(shot.shot_id)

    def _measure_sharpness(self) -> None:
        shot = self._selected_shot()
        if shot is None:
            self._photo_error("Selezionare uno scatto per misurare la nitidezza.")
            return
        self.photos.measure_sharpness(shot.shot_id)

    def _measurement_received(self, result: ExposureOut | SharpnessOut) -> None:
        for index in range(self.photo_grid.count()):
            item = self.photo_grid.item(index)
            shot = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(shot, ShotOut) and shot.shot_id == result.shot_id:
                if isinstance(result, ExposureOut):
                    shot.exposure = result
                else:
                    shot.sharpness = result
                item.setData(Qt.ItemDataRole.UserRole, shot)
                break
        self._show_details(self.photo_grid.currentItem(), None)

    @staticmethod
    def _exposure_text(shot: ShotOut) -> str:
        result = shot.exposure
        if not isinstance(result, ExposureOut):
            return "\nEsposizione anteprima: non ancora misurata"
        return (
            f"\n\nEsposizione anteprima ({result.width}x{result.height}):\n"
            f"Indice: {result.score:.1f}/100 (non qualita' complessiva)\n"
            f"Alte luci sature: {result.highlights_fraction:.1%}\n"
            f"Ombre chiuse: {result.shadows_fraction:.1%}\n"
            f"Luminosita' media: {result.mean_luma:.1%}\n"
            f"Metodo: {result.analyzer_version}\n"
            "Indicatori JPEG, non clipping del sensore RAW."
        )

    @staticmethod
    def _sharpness_text(shot: ShotOut) -> str:
        result = shot.sharpness
        if not isinstance(result, SharpnessOut):
            return "\nNitidezza anteprima: non ancora misurata"
        return (
            f"\n\nNitidezza anteprima ({result.width}x{result.height}):\n"
            f"Varianza Laplaciano: {result.laplacian_variance:.6g}\n"
            f"Energia gradienti: {result.gradient_energy:.6g}\n"
            f"Metodo: {result.analyzer_version}\n"
            "Dettaglio globale JPEG, non fuoco del soggetto o voto fotografico.\n"
            "Texture, rumore e compressione possono influenzare le misure."
        )

    def _show_details(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        self._enable_actions()
        if current is None:
            self.details_label.setText("Seleziona uno scatto per visualizzare i dettagli.")
            return
        shot = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(shot, ShotOut):
            self.details_label.setText("Metadati dello scatto non disponibili.")
            return
        status = self._review_status(shot)
        self.review_combo.setCurrentIndex(self.review_combo.findData(status.value))
        if not shot.files:
            self.details_label.setText(f"Stato: {REVIEW_LABELS[status]}\nMetadati non disponibili.")
            return
        metadata = shot.files[0].metadata
        group = str(shot.group_id) if isinstance(shot.group_id, uuid.UUID) else "senza raffica"
        self.details_label.setText(
            f"File: {len(shot.files)}\nFotocamera: {metadata.camera_model or '-'}\n"
            f"Obiettivo: {metadata.lens or '-'}\nISO: {metadata.iso or '-'}\n"
            f"Data: {shot.capture_time.isoformat() if shot.capture_time is not None else '-'}\n"
            f"Stato: {REVIEW_LABELS[status]} (revisione manuale)\n"
            f"Gruppo: {group}\n"
            "Qualita': non ancora valutata" + self._exposure_text(shot) + self._sharpness_text(shot)
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.closing.emit()
        super().closeEvent(event)
