"""Qt bridge to the generated API client; HTTP never runs on the UI thread."""

from __future__ import annotations

import httpx
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from shotkeepr.desktop.api_client import AuthenticatedClient
from shotkeepr.desktop.api_client.api.health.get_health_api_v1_health_get import sync as health
from shotkeepr.desktop.api_client.api.settings.get_settings_api_v1_settings_get import (
    sync as get_settings,
)
from shotkeepr.desktop.api_client.api.settings.patch_settings_api_v1_settings_patch import (
    sync as patch_settings,
)
from shotkeepr.desktop.api_client.errors import UnexpectedStatus
from shotkeepr.desktop.api_client.models import SettingsOut, SettingsPatch, Theme


class RequestWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, url: str, token: str, theme: Theme | None, parent: QObject) -> None:
        super().__init__(parent)
        self._url = url
        self._token = token
        self._theme = theme

    def run(self) -> None:
        try:
            with AuthenticatedClient(
                base_url=self._url,
                token=self._token,
                timeout=httpx.Timeout(2.0, connect=1.0),
                raise_on_unexpected_status=True,
                httpx_args={"trust_env": False},
            ) as client:
                if self._theme is None:
                    result = health(client=client)
                    if result is None or result.status != "ok":
                        raise ValueError("Il nucleo non e' pronto")
                    settings = get_settings(client=client)
                else:
                    settings = patch_settings(client=client, body=SettingsPatch(theme=self._theme))
                if not isinstance(settings, SettingsOut):
                    raise ValueError("Risposta impostazioni non valida")
                Theme(settings.theme)
        except UnexpectedStatus as exc:
            self.failed.emit(f"Il nucleo ha risposto con errore HTTP {exc.status_code}")
        except httpx.HTTPError:
            self.failed.emit("Nucleo non raggiungibile. Controllare la connessione e riprovare.")
        except (ValueError, TypeError, KeyError):
            self.failed.emit("Risposta del nucleo non compatibile con questa applicazione.")
        else:
            self.succeeded.emit(settings)


class CoreConnection(QObject):
    settings_received = Signal(object)
    status_changed = Signal(bool, str)
    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._url = ""
        self._token = ""
        self._worker: RequestWorker | None = None
        self._closing = False
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.refresh)

    def connect_to(self, url: str, token: str) -> None:
        self._url, self._token = url, token
        self._timer.start()
        self.refresh()

    def refresh(self) -> None:
        self._request(None)

    def set_theme(self, theme: Theme) -> None:
        self._request(theme)

    def _request(self, theme: Theme | None) -> None:
        if self._closing or self._worker is not None:
            return
        if not self._url:
            self.status_changed.emit(False, "Nucleo non avviato. Riavviare l'applicazione.")
            return
        worker = RequestWorker(self._url, self._token, theme, self)
        self._worker = worker
        worker.succeeded.connect(self._success)
        worker.failed.connect(self._failure)
        worker.finished.connect(self._finished)
        self.busy_changed.emit(True)
        worker.start()

    def _success(self, settings: SettingsOut) -> None:
        if not self._closing:
            self.settings_received.emit(settings)
            self.status_changed.emit(True, "Nucleo connesso")

    def _failure(self, message: str) -> None:
        if not self._closing:
            self.status_changed.emit(False, message)

    def _finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self.busy_changed.emit(False)

    def shutdown(self) -> None:
        self._closing = True
        self._timer.stop()
        if self._worker is not None:
            self._worker.wait()
            self._finished()


__all__ = ["CoreConnection"]
