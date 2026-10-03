"""Avvio reale del nucleo, bind esplicito e protezione dei contratti di deployment."""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import yaml

from shotkeepr.core.__main__ import main
from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.migrate import upgrade_to_head
from shotkeepr.core.adapters.persistence.settings import SqlSettingsRepository
from shotkeepr.core.adapters.secrets.stores import EnvSecretStore
from shotkeepr.core.api.server import BIND_HOSTS, prepare_server
from shotkeepr.core.application.configuration import ConfigurationService

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def service(tmp_path: Path) -> Iterator[ConfigurationService]:
    db = Database.at(tmp_path / "test.db")
    try:
        upgrade_to_head(db.url)
        yield ConfigurationService(SqlSettingsRepository(db), EnvSecretStore({}))
    finally:
        db.dispose()


def test_container_bind_preserves_authentication(
    service: ConfigurationService, tmp_path: Path
) -> None:
    config, handle = prepare_server(service, tmp_path / "run", port=8321, host=BIND_HOSTS[1])
    assert config.host == handle.host == BIND_HOSTS[1]
    assert config.port == handle.port == 8321
    assert handle.token_path.stat().st_mode & 0o777 == 0o600
    assert handle.token_path.read_text(encoding="utf-8") == handle.token


@pytest.mark.parametrize(
    ("host", "port"), [("192.0.2.1", 8321), (BIND_HOSTS[0], 0), (BIND_HOSTS[0], 65536)]
)
def test_invalid_configuration_does_not_write_credentials(
    service: ConfigurationService, tmp_path: Path, host: str, port: int
) -> None:
    runtime = tmp_path / "run"
    with pytest.raises(ValueError):
        prepare_server(service, runtime, host=host, port=port)
    assert not runtime.exists()


@pytest.mark.parametrize("command", ["serve", "healthcheck"])
@pytest.mark.parametrize("port", ["0", "-1", "65536", "abc"])
def test_cli_rejects_invalid_ports(command: str, port: str) -> None:
    with pytest.raises(SystemExit) as exc:
        main([command, "--port", port])
    assert exc.value.code == 2


def test_cli_rejects_arbitrary_bind() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["serve", "--host", "192.0.2.1"])
    assert exc.value.code == 2


@pytest.mark.parametrize("host", BIND_HOSTS)
def test_native_startup_healthcheck_and_authenticated_settings(tmp_path: Path, host: str) -> None:
    runtime = tmp_path / "run"
    with subprocess.Popen(  # noqa: S603 -- processo del nucleo con argomenti fissi
        [
            sys.executable,
            "-m",
            "shotkeepr.core",
            "serve",
            "--host",
            host,
            "--runtime-dir",
            str(runtime),
            "--data-dir",
            str(tmp_path / "data"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as process:
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                assert process.poll() is None, "Il processo del nucleo si e' arrestato"
                if (runtime / "api.port").exists() and main(
                    [
                        "healthcheck",
                        "--runtime-dir",
                        str(runtime),
                    ]
                ) == 0:
                    break
                time.sleep(0.05)
            else:
                pytest.fail("Il nucleo non e' diventato disponibile")

            port = int((runtime / "api.port").read_text(encoding="utf-8"))
            token = (runtime / "api.token").read_text(encoding="utf-8")
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
                assert client.get("/api/v1/settings").status_code == 401
                assert (
                    client.get(
                        "/api/v1/settings",
                        headers={"Authorization": f"Bearer {token}"},
                    ).json()["edition"]
                    == "OPEN"
                )
                assert (
                    client.patch(
                        "/api/v1/settings",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"theme": "LIGHT"},
                    ).json()["theme"]
                    == "LIGHT"
                )
        finally:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
    # Uvicorn rilancia SIGTERM dopo il graceful shutdown su POSIX.
    terminated = 1 if sys.platform == "win32" else -signal.SIGTERM
    assert process.returncode in (0, terminated)
    db = Database.at(tmp_path / "data" / "shotkeepr.db")
    try:
        saved = SqlSettingsRepository(db).load()
        assert saved is not None
        assert saved.theme.value == "LIGHT"
    finally:
        db.dispose()


def test_compose_protects_api_photos_models_and_runtime() -> None:
    compose = yaml.safe_load((ROOT / "docker" / "compose.yaml").read_text(encoding="utf-8"))
    core = compose["services"]["core"]
    qdrant = compose["services"]["qdrant"]
    assert core["ports"] == ["127.0.0.1:${SHOTKEEPR_PORT:-8321}:8321"]
    assert core["depends_on"]["qdrant"]["condition"] == "service_healthy"
    assert core["stop_grace_period"] == "35s"
    assert "ports" not in qdrant
    for service_config in (core, qdrant):
        assert service_config["read_only"] is True
        assert service_config["cap_drop"] == ["ALL"]
        assert service_config["security_opt"] == ["no-new-privileges:true"]
        assert (ROOT / service_config["build"]["dockerfile"]).is_file()
    mounts = {mount["target"]: mount for mount in core["volumes"] if isinstance(mount, dict)}
    assert mounts["/photos"]["read_only"] is True
    assert mounts["/models"]["read_only"] is True
    assert not mounts["/run/shotkeepr"].get("read_only", False)
    assert all(mount["bind"]["create_host_path"] is False for mount in mounts.values())
    assert set(compose["volumes"]) == {"core-data", "qdrant-data"}


def test_xmp_write_access_is_an_explicit_separate_override() -> None:
    override = yaml.safe_load((ROOT / "docker" / "compose.xmp.yaml").read_text(encoding="utf-8"))
    assert set(override["services"]) == {"core"}
    core = override["services"]["core"]
    assert set(core) == {"volumes"}
    assert len(core["volumes"]) == 1
    mount = core["volumes"][0]
    assert mount["target"] == "/photos"
    assert mount["read_only"] is False
    assert mount["bind"]["create_host_path"] is False


def test_cuda_is_an_opt_in_override() -> None:
    override = yaml.safe_load((ROOT / "docker" / "compose.cuda.yaml").read_text(encoding="utf-8"))
    core = override["services"]["core"]
    assert core["build"]["args"]["RUNTIME"] == "cuda"
    assert core["deploy"]["resources"]["reservations"]["devices"] == [
        {"driver": "nvidia", "count": "all", "capabilities": ["gpu"]},
    ]


def test_container_build_is_locked_and_excludes_the_gui() -> None:
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "--frozen --no-dev --no-editable --package shotkeepr-core" in dockerfile
    assert "libimage-exiftool-perl" in dockerfile
    assert '--extra "$RUNTIME"' in dockerfile
    assert "nvidia/cuda:13.0.2-cudnn-runtime-ubuntu22.04" in dockerfile
    assert "USER ${APP_UID}:${APP_GID}" in dockerfile
    assert '["shotkeepr-core", "healthcheck", "--port", "8321"]' in dockerfile
    qdrant = (ROOT / "docker" / "Dockerfile.qdrant").read_text(encoding="utf-8")
    assert "QDRANT__TELEMETRY_DISABLED=true" in qdrant
    assert "QDRANT_INIT_FILE_PATH=/qdrant/storage/.qdrant-initialized" in qdrant
    assert "USER 1000:1000" in qdrant
    assert (ROOT / "models" / ".gitkeep").is_file()
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert ignore.startswith("**\n")
    assert "!packages/desktop/src" not in ignore
    assert "!packages/core/src/**" in ignore
