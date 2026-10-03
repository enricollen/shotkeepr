import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.adapters.grouping.factory import grouping_service
from shotkeepr.core.adapters.persistence.settings import SqlSettingsRepository
from shotkeepr.core.adapters.secrets.stores import EnvSecretStore
from shotkeepr.core.api.app import create_app
from shotkeepr.core.api.import_jobs import ImportJobs
from shotkeepr.core.application.configuration import ConfigurationService
from shotkeepr.core.application.ingestion import PhotoImportService
from shotkeepr.core.domain.catalog import Session, SessionStatus
from shotkeepr.core.domain.catalog.grouping import BurstGrouping

from ..quality.conftest import ExposureCatalog
from .conftest import shot

TOKEN = "grouping-test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(catalog: ExposureCatalog) -> Iterator[TestClient]:
    def unused_import() -> PhotoImportService:
        pytest.fail("grouping must never start an import")

    catalog.shots.add_many(
        [shot(catalog.session.session_id, seconds) for seconds in (0, 1, 2, 20, 21)]
    )
    jobs = ImportJobs(unused_import, catalog.sessions, catalog.shots, catalog.previews)
    configuration = ConfigurationService(SqlSettingsRepository(catalog.db), EnvSecretStore({}))
    with TestClient(
        create_app(
            configuration,
            TOKEN,
            import_jobs=jobs,
            grouping_service=grouping_service(catalog.db),
        )
    ) as client:
        yield client


def _root(catalog: ExposureCatalog) -> str:
    return f"/api/v1/photos/sessions/{catalog.session.session_id}"


def test_grouping_is_explicit_authenticated_and_saved_in_session_details(
    client: TestClient, catalog: ExposureCatalog
) -> None:
    root = _root(catalog)
    assert client.get(root + "/groups").status_code == 401
    assert client.post(root + "/groups/bursts", json={"gap_seconds": 2}).status_code == 401
    initial = client.get(root + "/groups", headers=HEADERS).json()
    assert initial["groups"] == []
    assert initial["gap_seconds"] is None
    assert initial["ungrouped_shots"] == 6
    saved = client.post(root + "/groups/bursts", headers=HEADERS, json={"gap_seconds": 2})
    assert saved.status_code == 200
    result = saved.json()
    assert [group["shots"] for group in result["groups"]] == [3, 2]
    assert result["ungrouped_shots"] == 1
    assert result["method_version"] == "camera-time-bursts-v1"
    assert result["gap_seconds"] == 2
    assert client.get(root + "/groups", headers=HEADERS).json() == result
    assert client.post(root + "/groups/bursts", headers=HEADERS, json={}).json() == result
    details = client.get(root, headers=HEADERS).json()
    assert details["grouping"] == result
    assert details["status"] == "IMPORTED"
    assert catalog.sessions.get(catalog.session.session_id) == catalog.session


def test_group_filter_is_applied_to_the_entire_session_before_pagination(
    client: TestClient, catalog: ExposureCatalog
) -> None:
    root = _root(catalog)
    grouping = client.post(root + "/groups/bursts", headers=HEADERS, json={}).json()
    group_id = grouping["groups"][0]["group_id"]
    first = client.get(
        root + "/shots", headers=HEADERS, params={"group_id": group_id, "limit": 2}
    ).json()
    assert first["total"] == 3
    assert len(first["items"]) == 2
    assert all(item["group_id"] == group_id for item in first["items"])
    second = client.get(
        root + "/shots", headers=HEADERS, params={"group_id": group_id, "limit": 2, "offset": 2}
    ).json()
    assert second["total"] == 3 and second["offset"] == 2
    assert len(second["items"]) == 1
    assert second["items"][0]["shot_id"] not in {item["shot_id"] for item in first["items"]}
    without = client.get(root + "/shots", headers=HEADERS, params={"ungrouped": "true"}).json()
    assert without["total"] == 1
    assert without["items"][0]["shot_id"] == str(catalog.shot.shot_id)
    assert without["items"][0]["group_id"] is None
    assert client.get(root + "/shots", headers=HEADERS).json()["total"] == 6


def test_invalid_or_foreign_groups_do_not_appear_as_successful_empty_pages(
    client: TestClient, catalog: ExposureCatalog
) -> None:
    root = _root(catalog)
    unknown = str(uuid.uuid4())
    assert (
        client.get(root + "/shots", headers=HEADERS, params={"group_id": unknown}).status_code
        == 404
    )
    assert (
        client.get(
            root + "/shots", headers=HEADERS, params={"group_id": unknown, "ungrouped": "true"}
        ).status_code
        == 400
    )
    assert (
        client.get(root + "/shots", headers=HEADERS, params={"group_id": "invalid"}).status_code
        == 422
    )
    other = Session(catalog.session.source_folder, status=SessionStatus.IMPORTED)
    catalog.sessions.add(other)
    catalog.shots.add_many([shot(other.session_id, 0), shot(other.session_id, 1)])
    grouping = grouping_service(catalog.db).regroup(other.session_id, 2)
    assert (
        client.get(
            root + "/shots", headers=HEADERS, params={"group_id": str(grouping.groups[0].group_id)}
        ).status_code
        == 404
    )


@pytest.mark.parametrize("gap", [0, -1, 60.01, True, "2"])
def test_invalid_thresholds_do_not_modify_the_catalog(
    client: TestClient, catalog: ExposureCatalog, gap: object
) -> None:
    failed = client.post(
        _root(catalog) + "/groups/bursts", headers=HEADERS, json={"gap_seconds": gap}
    )
    assert failed.status_code == 422
    assert grouping_service(catalog.db).get(catalog.session.session_id).grouped_at is None


def test_failures_are_logged_and_previous_groups_remain(
    client: TestClient,
    catalog: ExposureCatalog,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    root = _root(catalog)
    saved = client.post(root + "/groups/bursts", headers=HEADERS, json={}).json()

    def fail(session_id: uuid.UUID, gap_seconds: float) -> BurstGrouping:
        raise SQLAlchemyError("disk failure")

    monkeypatch.setattr(client.app.state.grouping_service.repository, "regroup", fail)
    response = client.post(root + "/groups/bursts", headers=HEADERS, json={"gap_seconds": 1})
    assert response.status_code == 503
    assert "raggruppamento" in caplog.text
    assert client.get(root + "/groups", headers=HEADERS).json() == saved


def test_missing_session_and_unconfigured_service_are_explicit(
    client: TestClient, catalog: ExposureCatalog
) -> None:
    unknown = f"/api/v1/photos/sessions/{uuid.uuid4()}"
    assert client.get(unknown + "/groups", headers=HEADERS).status_code == 404
    assert client.post(unknown + "/groups/bursts", headers=HEADERS, json={}).status_code == 404
    configuration = ConfigurationService(SqlSettingsRepository(catalog.db), EnvSecretStore({}))
    with TestClient(create_app(configuration, TOKEN)) as bare:
        assert bare.get("/api/v1/health").status_code == 200
        assert bare.get(_root(catalog) + "/groups", headers=HEADERS).status_code == 503
        assert (
            bare.post(_root(catalog) + "/groups/bursts", headers=HEADERS, json={}).status_code
            == 503
        )
