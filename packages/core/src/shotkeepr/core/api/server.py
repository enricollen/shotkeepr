"""Avvio del server HTTP locale: bind su 127.0.0.1, token scritto su file (ADR-003)."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from shotkeepr.core.api.app import create_app
from shotkeepr.core.api.auth import generate_token, write_token_file
from shotkeepr.core.application.configuration import ConfigurationService

LOCALHOST = "127.0.0.1"


@dataclass(frozen=True, slots=True)
class ServerHandle:
    """Informazioni di avvio esposte alla GUI tramite file locali."""

    host: str
    port: int
    token: str
    token_path: Path
    port_path: Path


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((LOCALHOST, 0))
        return int(s.getsockname()[1])


def prepare_server(
    configuration_service: ConfigurationService,
    runtime_dir: Path,
    *,
    port: int | None = None,
) -> tuple[uvicorn.Config, ServerHandle]:
    """Costruisce la configurazione uvicorn e scrive token/porta per la GUI."""
    token = generate_token()
    chosen_port = port if port is not None else find_free_port()
    token_path = runtime_dir / "api.token"
    port_path = runtime_dir / "api.port"
    write_token_file(token_path, token)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    port_path.write_text(str(chosen_port), encoding="utf-8")

    app = create_app(configuration_service, token)
    config = uvicorn.Config(app, host=LOCALHOST, port=chosen_port, log_level="warning")
    handle = ServerHandle(
        host=LOCALHOST,
        port=chosen_port,
        token=token,
        token_path=token_path,
        port_path=port_path,
    )
    return config, handle


def serve(
    configuration_service: ConfigurationService,
    runtime_dir: Path,
    *,
    port: int | None = None,
) -> None:
    """Avvia il server in modo bloccante (chiamato dal comando `shotkeepr-core serve`)."""
    config, _handle = prepare_server(configuration_service, runtime_dir, port=port)
    uvicorn.Server(config).run()
