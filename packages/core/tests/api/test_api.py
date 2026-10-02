"""Test di contratto dell'API /api/v1 (F1.D2.WP2.A4)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.migrate import upgrade_to_head
from shotkeepr.core.adapters.persistence.settings import SqlSettingsRepository
from shotkeepr.core.api.app import create_app
from shotkeepr.core.api.events import Event, EventKind
from shotkeepr.core.application.configuration import ConfigurationService

TOKEN = "test-token-123"


class _MemorySecretStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, ref: str) -> str | None:
        return self._data.get(ref)

    def set(self, ref: str, secret: str) -> None:
        self._data[ref] = secret

    def delete(self, ref: str) -> None:
        self._data.pop(ref, None)


@pytest.fixture
def client(tmp_path: object) -> Iterator[TestClient]:
    db = Database.at(tmp_path / "test.db")  # type: ignore[operator]
    upgrade_to_head(db.url)
    service = ConfigurationService(SqlSettingsRepository(db), _MemorySecretStore())
    app = create_app(service, TOKEN)
    with TestClient(app) as test_client:
        yield test_client
    db.dispose()


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_settings_requires_token(client: TestClient) -> None:
    response = client.get("/api/v1/settings")
    assert response.status_code == 401


def test_settings_rejects_wrong_token(client: TestClient) -> None:
    response = client.get("/api/v1/settings", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_settings_roundtrip_with_token(client: TestClient) -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = client.get("/api/v1/settings", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["theme"] == "DARK"
    assert body["edition"] == "OPEN"


def test_settings_patch_updates_only_given_fields(client: TestClient) -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = client.patch("/api/v1/settings", json={"theme": "LIGHT"}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["theme"] == "LIGHT"
    assert body["edition"] == "OPEN"


def test_settings_patch_rejects_invalid_theme(client: TestClient) -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = client.patch("/api/v1/settings", json={"theme": "PURPLE"}, headers=headers)
    assert response.status_code == 422


def test_openapi_contract_exposes_versioned_paths(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) >= {"/api/v1/health", "/api/v1/settings"}
    assert schema["info"]["version"]


def test_events_websocket_requires_token(client: TestClient) -> None:
    with (
        pytest.raises(Exception, match=r".*"),
        client.websocket_connect("/api/v1/events") as ws,
    ):
        ws.receive_json()


def test_events_websocket_delivers_published_events(client: TestClient) -> None:
    with client.websocket_connect(f"/api/v1/events?token={TOKEN}") as ws:
        client.app.state.event_bus.publish(  # type: ignore[attr-defined]
            Event(kind=EventKind.PROGRESS, payload={"percent": 42})
        )
        message = ws.receive_json()
    assert message["kind"] == "PROGRESS"
    assert message["payload"] == {"percent": 42}
