"""Directory dati dell'applicazione, per piattaforma (nessuna dipendenza esterna)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "ShotKeepr"


def app_data_dir() -> Path:
    """Radice per database, log e file di runtime locali, specifica per piattaforma."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    root = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return root / "shotkeepr"


def db_path() -> Path:
    return app_data_dir() / "shotkeepr.db"


def runtime_dir() -> Path:
    return app_data_dir() / "run"


def log_dir() -> Path:
    return app_data_dir() / "logs"
