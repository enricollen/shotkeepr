"""Server locale: loopback di default, bind esplicito per Docker (ADR-003, ADR-004)."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from shotkeepr.core.api.app import create_app
from shotkeepr.core.api.auth import generate_token, write_token_file
from shotkeepr.core.api.import_jobs import ImportJobs
from shotkeepr.core.application.configuration import ConfigurationService
from shotkeepr.core.application.exposure import ExposureService
from shotkeepr.core.application.grouping import GroupingService
from shotkeepr.core.application.review import ReviewService
from shotkeepr.core.application.sharpness import SharpnessService

LOCALHOST = "127.0.0.1"
BIND_HOSTS = (LOCALHOST, "0.0.0.0")  # noqa: S104 -- solo opt-in per il container


@dataclass(frozen=True, slots=True)
class ServerHandle:
    """Informazioni di avvio esposte alla GUI tramite file locali."""

    host: str
    port: int
    token: str
    token_path: Path
    port_path: Path


def find_free_port(host: str = LOCALHOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def prepare_server(
    configuration_service: ConfigurationService,
    runtime_dir: Path,
    *,
    port: int | None = None,
    host: str = LOCALHOST,
    import_jobs: ImportJobs | None = None,
    exposure_service: ExposureService | None = None,
    review_service: ReviewService | None = None,
    grouping_service: GroupingService | None = None,
    sharpness_service: SharpnessService | None = None,
) -> tuple[uvicorn.Config, ServerHandle]:
    """Costruisce la configurazione uvicorn e scrive token/porta per la GUI."""
    if host not in BIND_HOSTS:
        raise ValueError(f"host non supportato: {host}")
    if port is not None and not 0 < port < 65536:
        raise ValueError("la porta deve essere compresa tra 1 e 65535")
    token = generate_token()
    chosen_port = port if port is not None else find_free_port(host)
    token_path = runtime_dir / "api.token"
    port_path = runtime_dir / "api.port"
    write_token_file(token_path, token)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    port_path.write_text(str(chosen_port), encoding="utf-8")

    app = create_app(
        configuration_service,
        token,
        import_jobs=import_jobs,
        exposure_service=exposure_service,
        review_service=review_service,
        grouping_service=grouping_service,
        sharpness_service=sharpness_service,
    )
    config = uvicorn.Config(app, host=host, port=chosen_port, log_level="warning")
    handle = ServerHandle(
        host=host,
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
    host: str = LOCALHOST,
    import_jobs: ImportJobs | None = None,
    exposure_service: ExposureService | None = None,
    review_service: ReviewService | None = None,
    grouping_service: GroupingService | None = None,
    sharpness_service: SharpnessService | None = None,
) -> None:
    """Avvia il server in modo bloccante (chiamato dal comando `shotkeepr-core serve`)."""
    config, _handle = prepare_server(
        configuration_service,
        runtime_dir,
        port=port,
        host=host,
        import_jobs=import_jobs,
        exposure_service=exposure_service,
        review_service=review_service,
        grouping_service=grouping_service,
        sharpness_service=sharpness_service,
    )
    uvicorn.Server(config).run()
