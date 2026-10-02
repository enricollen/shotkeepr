"""Native desktop entry point with an owned core or an explicit local endpoint."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from shotkeepr.desktop import __version__
from shotkeepr.desktop.connection import CoreConnection
from shotkeepr.desktop.runtime import CoreRuntime
from shotkeepr.desktop.window import MainWindow


def local_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Porta del nucleo non valida") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port == 0
    ):
        raise argparse.ArgumentTypeError("Usare un'origine locale http://127.0.0.1:PORTA")
    return value.rstrip("/")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shotkeepr")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--core-url", type=local_url)
    parser.add_argument("--token-file", type=Path)
    args = parser.parse_args(argv)
    if bool(args.core_url) != bool(args.token_file):
        parser.error("--core-url e --token-file devono essere usati insieme")
    token = ""
    if args.token_file:
        try:
            token = args.token_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            parser.error("Impossibile leggere il file del token")
        if not token or not token.isascii() or any(char.isspace() for char in token):
            parser.error("Token locale non valido")

    existing = QApplication.instance()
    if existing is None:
        # Qt 6 scales widgets automatically; preserve fractional display scaling.
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = QApplication([sys.argv[0]])
    elif isinstance(existing, QApplication):
        app = existing
    else:
        raise RuntimeError("L'applicazione Qt esistente non supporta i widget")
    app.setApplicationName("ShotKeepr")
    app.setOrganizationName("ShotKeepr")
    app.setStyle("Fusion")
    connection = CoreConnection(app)
    runtime = CoreRuntime(app)
    window = MainWindow(app, connection)
    window.closing.connect(connection.shutdown)
    window.closing.connect(runtime.stop)
    if args.core_url:
        QTimer.singleShot(0, partial(connection.connect_to, args.core_url, token))
    else:
        runtime.ready.connect(connection.connect_to)
        runtime.failed.connect(partial(window.set_connection_status, False))
        QTimer.singleShot(0, runtime.start)
    window.show()
    try:
        return app.exec()
    finally:
        connection.shutdown()
        runtime.stop()
        window.close()


if __name__ == "__main__":
    raise SystemExit(main())
