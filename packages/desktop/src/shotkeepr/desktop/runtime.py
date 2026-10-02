"""Own the native core subprocess without importing its Python modules."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class CoreRuntime(QObject):
    ready = Signal(str, str)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None, *, data_dir: Path | None = None) -> None:
        super().__init__(parent)
        self._data_dir = data_dir
        self._directory: tempfile.TemporaryDirectory[str] | None = None
        self._deadline = 0.0
        self._stopping = False
        self._process = QProcess(self)
        self._process.errorOccurred.connect(self._process_error)
        self._process.finished.connect(self._exited)
        self._process.readyReadStandardOutput.connect(self._discard_output)
        self._process.readyReadStandardError.connect(self._discard_output)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._directory = tempfile.TemporaryDirectory(prefix="shotkeepr-")
        self._deadline = time.monotonic() + 20.0
        arguments = ["-m", "shotkeepr.core", "serve", "--runtime-dir", self._directory.name]
        if self._data_dir is not None:
            arguments.extend(["--data-dir", str(self._data_dir)])
        self._process.start(sys.executable, arguments)
        self._timer.start()

    def _poll(self) -> None:
        if self._directory is None:
            return
        directory = Path(self._directory.name)
        token_path, port_path = directory / "api.token", directory / "api.port"
        if token_path.exists() and port_path.exists():
            try:
                token = token_path.read_text(encoding="utf-8").strip()
                port = int(port_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._timer.stop()
                self.failed.emit("Impossibile leggere i dati di avvio del nucleo.")
                return
            if token and 0 < port < 65536:
                self._timer.stop()
                self.ready.emit(f"http://127.0.0.1:{port}", token)
                return
        if time.monotonic() >= self._deadline:
            self._timer.stop()
            self.failed.emit("Avvio del nucleo scaduto. Riavviare l'applicazione.")
            self.stop()

    def _process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._timer.stop()
            self.failed.emit("Impossibile avviare il nucleo. Installare shotkeepr-core.")

    def _exited(self, code: int, _status: QProcess.ExitStatus) -> None:
        self._timer.stop()
        if not self._stopping:
            self.failed.emit(f"Il nucleo si e' arrestato (codice {code}).")

    def _discard_output(self) -> None:
        self._process.readAllStandardOutput()
        self._process.readAllStandardError()

    def stop(self) -> None:
        self._stopping = True
        self._timer.stop()
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.terminate()
            if not self._process.waitForFinished(2000):
                self._process.kill()
                self._process.waitForFinished()
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
