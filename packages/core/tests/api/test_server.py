"""Test del runtime di avvio dell'API: file token/porta (F1.D2.WP2.A1)."""

from __future__ import annotations

from pathlib import Path

from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.migrate import upgrade_to_head
from shotkeepr.core.adapters.persistence.settings import SqlSettingsRepository
from shotkeepr.core.api.auth import read_token_file
from shotkeepr.core.api.server import LOCALHOST, find_free_port, prepare_server
from shotkeepr.core.application.configuration import ConfigurationService


class _MemorySecretStore:
    def get(self, ref: str) -> str | None:
        return None

    def set(self, ref: str, secret: str) -> None:
        return None

    def delete(self, ref: str) -> None:
        return None


def test_find_free_port_returns_usable_port() -> None:
    port = find_free_port()
    assert 1024 < port < 65536


def test_prepare_server_binds_localhost_and_writes_token(tmp_path: Path) -> None:
    db = Database.at(tmp_path / "test.db")
    upgrade_to_head(db.url)
    service = ConfigurationService(SqlSettingsRepository(db), _MemorySecretStore())
    runtime_dir = tmp_path / "run"

    config, handle = prepare_server(service, runtime_dir)

    assert config.host == LOCALHOST
    assert handle.token_path.exists()
    assert handle.port_path.read_text(encoding="utf-8") == str(handle.port)
    assert read_token_file(handle.token_path) == handle.token
    # Il file del token non deve essere leggibile da altri utenti.
    mode = handle.token_path.stat().st_mode & 0o777
    assert mode == 0o600
    db.dispose()
