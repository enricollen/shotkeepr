"""Test di contratto del client tipizzato verso il nucleo reale (F1.D2.WP2.A3/A4).

Avvia `shotkeepr-core serve` come processo separato: la GUI e il nucleo comunicano
solo via HTTP/WebSocket (ADR-002), quindi qui non si importa mai `shotkeepr.core`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from shotkeepr.desktop.api_client import AuthenticatedClient, Client
from shotkeepr.desktop.api_client.api.health.get_health_api_v1_health_get import (
    sync as get_health,
)
from shotkeepr.desktop.api_client.api.settings.get_settings_api_v1_settings_get import (
    sync_detailed as get_settings_detailed,
)

STARTUP_TIMEOUT_S = 20.0


@pytest.fixture
def core_server(tmp_path: Path) -> Iterator[tuple[str, str]]:
    data_dir = tmp_path / "data"
    env = {**os.environ, "XDG_DATA_HOME": str(data_dir)}
    process = subprocess.Popen(
        [sys.executable, "-m", "shotkeepr.core", "serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    token_path = data_dir / "shotkeepr" / "run" / "api.token"
    port_path = data_dir / "shotkeepr" / "run" / "api.port"
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    try:
        while time.monotonic() < deadline:
            if token_path.exists() and port_path.exists():
                break
            if process.poll() is not None:
                output = process.stdout.read().decode() if process.stdout else ""
                raise RuntimeError(f"shotkeepr-core serve terminato in anticipo:\n{output}")
            time.sleep(0.1)
        else:
            raise TimeoutError("timeout in attesa dell'avvio di shotkeepr-core serve")

        token = token_path.read_text(encoding="utf-8").strip()
        port = port_path.read_text(encoding="utf-8").strip()
        base_url = f"http://127.0.0.1:{port}"
        # L'avvio di uvicorn è asincrono rispetto alla scrittura dei file: un breve
        # margine evita richieste in corsa con il bind della socket.
        time.sleep(0.3)
        yield base_url, token
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def test_health_reachable_without_token(core_server: tuple[str, str]) -> None:
    base_url, _token = core_server
    client = Client(base_url=base_url)
    health = get_health(client=client)
    assert health is not None
    assert health.status == "ok"


def test_settings_requires_token(core_server: tuple[str, str]) -> None:
    base_url, _token = core_server
    client = Client(base_url=base_url)
    response = get_settings_detailed(client=client)
    assert response.status_code == 401


def test_settings_reachable_with_token(core_server: tuple[str, str]) -> None:
    base_url, token = core_server
    client = AuthenticatedClient(base_url=base_url, token=token)
    response = get_settings_detailed(client=client)
    assert response.status_code == 200
    assert response.parsed is not None
    assert response.parsed.edition == "OPEN"
