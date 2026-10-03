"""Contratti della sonda di salute e del comando headless."""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path

import pytest

from shotkeepr.core import __main__ as entrypoint
from shotkeepr.core.api import healthcheck
from shotkeepr.core.api.healthcheck import HealthCheckError, check_health


@dataclass
class _Response:
    status: int = 200
    body: bytes = b'{"status":"ok"}'

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class _Connection:
    def __init__(self) -> None:
        self.response = _Response()
        self.requested: tuple[str, str] | None = None
        self.closed = False

    def request(self, method: str, path: str) -> None:
        self.requested = method, path

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def connection(monkeypatch: pytest.MonkeyPatch) -> _Connection:
    connection = _Connection()

    def factory(host: str, port: int, *, timeout: float) -> _Connection:
        assert host == "127.0.0.1"
        assert port == 8321
        assert timeout == 2.0
        return connection

    monkeypatch.setattr(healthcheck, "HTTPConnection", factory)
    return connection


def test_healthcheck_requests_local_health_and_closes(connection: _Connection) -> None:
    check_health(8321)
    assert connection.requested == ("GET", "/api/v1/health")
    assert connection.closed


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (503, b"{}", HealthCheckError),
        (302, b"{}", HealthCheckError),
        (200, b'{"status":"error"}', HealthCheckError),
        (200, b"[]", HealthCheckError),
        (200, b"null", HealthCheckError),
        (200, b"not-json", json.JSONDecodeError),
        (200, b"\xff", UnicodeDecodeError),
        (200, b"x" * 4097, HealthCheckError),
    ],
)
def test_healthcheck_rejects_bad_responses_and_closes(
    connection: _Connection, status: int, body: bytes, error: type[Exception]
) -> None:
    connection.response = _Response(status, body)
    with pytest.raises(error):
        check_health(8321)
    assert connection.closed


def test_healthcheck_closes_on_connection_failure(
    monkeypatch: pytest.MonkeyPatch, connection: _Connection
) -> None:
    def unavailable(method: str, path: str) -> None:
        raise TimeoutError("timeout")

    monkeypatch.setattr(connection, "request", unavailable)
    with pytest.raises(TimeoutError):
        check_health(8321)
    assert connection.closed


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_healthcheck_rejects_invalid_port(port: int) -> None:
    with pytest.raises(ValueError, match="porta"):
        check_health(port)


def test_command_reads_runtime_port(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "api.port").write_text("8321", encoding="utf-8")
    calls: list[int] = []
    monkeypatch.setattr(entrypoint, "check_health", calls.append)
    monkeypatch.setattr(entrypoint, "runtime_dir", lambda: tmp_path)
    assert entrypoint.main(["healthcheck"]) == 0
    assert entrypoint.main(["healthcheck", "--runtime-dir", str(tmp_path)]) == 0
    assert calls == [8321, 8321]


def test_command_explicit_port_does_not_read_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(entrypoint, "check_health", calls.append)
    assert entrypoint.main(["healthcheck", "--port", "8321", "--runtime-dir", str(tmp_path)]) == 0
    assert calls == [8321]


@pytest.mark.parametrize("content", [None, "invalid", "0", "65536"])
def test_command_reports_unavailable_runtime(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str | None
) -> None:
    if content is not None:
        (tmp_path / "api.port").write_text(content, encoding="utf-8")
    assert entrypoint.main(["healthcheck", "--runtime-dir", str(tmp_path)]) == 1
    assert "Nucleo non disponibile:" in capsys.readouterr().err


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError("offline"),
        TimeoutError("timeout"),
        HTTPException("http"),
        HealthCheckError("unhealthy"),
        ValueError("json"),
    ],
)
def test_command_reports_probe_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    def unavailable(port: int) -> None:
        raise error

    monkeypatch.setattr(entrypoint, "check_health", unavailable)
    assert entrypoint.main(["healthcheck", "--port", "8321"]) == 1
    assert str(error) in capsys.readouterr().err
