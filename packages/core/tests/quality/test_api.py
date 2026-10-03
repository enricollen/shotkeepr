import uuid
from collections.abc import Iterator, Sequence

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.adapters.persistence.settings import SqlSettingsRepository
from shotkeepr.core.adapters.secrets.stores import EnvSecretStore
from shotkeepr.core.api.app import create_app
from shotkeepr.core.api.import_jobs import ImportJobs
from shotkeepr.core.application.configuration import ConfigurationService
from shotkeepr.core.application.ingestion import PhotoImportService
from shotkeepr.core.domain.quality.exposure import ExposureMeasurement

from .conftest import ExposureCatalog

TOKEN = "test-exposure-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(catalog: ExposureCatalog) -> Iterator[TestClient]:
    def unused_import() -> PhotoImportService:
        pytest.fail("measuring exposure must not start an import")

    jobs = ImportJobs(unused_import, catalog.sessions, catalog.shots, catalog.previews)
    configuration = ConfigurationService(SqlSettingsRepository(catalog.db), EnvSecretStore({}))
    with TestClient(
        create_app(configuration, TOKEN, import_jobs=jobs, exposure_service=catalog.service)
    ) as client:
        yield client


def _path(catalog: ExposureCatalog) -> str:
    return f"/api/v1/photos/shots/{catalog.shot.shot_id}/exposure"


def test_explicit_measurement_is_authenticated_and_visible_in_saved_pages(
    client: TestClient, catalog: ExposureCatalog
) -> None:
    path = _path(catalog)
    assert client.get(path).status_code == 401
    assert client.post(path).status_code == 401
    assert catalog.results.get(catalog.shot.shot_id) is None
    assert client.get(path, headers=HEADERS).status_code == 404
    measured = client.post(path, headers=HEADERS)
    assert measured.status_code == 200
    result = measured.json()
    assert result["score"] == 100
    assert result["analyzer_version"] == "preview-rgb-exposure-v1"
    assert result["source_fingerprint"] == catalog.shot.files[0].fingerprint
    assert client.post(path, headers=HEADERS).json() == result
    assert client.get(path, headers=HEADERS).json() == result
    assert catalog.analyzer.calls == 1
    page = client.get(
        f"/api/v1/photos/sessions/{catalog.session.session_id}/shots", headers=HEADERS
    ).json()
    assert page["items"][0]["exposure"] == result
    assert catalog.sessions.get(catalog.session.session_id) == catalog.session
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/v1/photos/shots/{shot_id}/exposure"]["post"]["operationId"] == (
        "measure_photo_exposure"
    )


def test_reading_a_photo_page_does_not_run_analysis(
    client: TestClient, catalog: ExposureCatalog
) -> None:
    response = client.get(
        f"/api/v1/photos/sessions/{catalog.session.session_id}/shots", headers=HEADERS
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["exposure"] is None
    assert catalog.analyzer.calls == 0


@pytest.mark.parametrize("method", ["get", "post"])
def test_unknown_shot_is_not_a_success(client: TestClient, method: str) -> None:
    path = f"/api/v1/photos/shots/{uuid.uuid4()}/exposure"
    assert client.request(method, path, headers=HEADERS).status_code == 404


@pytest.mark.parametrize("failure", ["missing", "corrupt"])
def test_bad_preview_returns_an_explicit_conflict_and_preserves_the_previous_measurement(
    client: TestClient, catalog: ExposureCatalog, failure: str
) -> None:
    path = _path(catalog)
    saved = client.post(path, headers=HEADERS).json()
    if failure == "missing":
        catalog.preview.unlink()
    else:
        catalog.preview.write_bytes(b"not a jpeg")
    failed = client.post(path, headers=HEADERS)
    assert failed.status_code == 409
    assert "anteprima" in failed.json()["detail"]
    assert client.get(path, headers=HEADERS).json() == saved


def test_write_failure_is_logged_not_reported_as_success(
    client: TestClient,
    catalog: ExposureCatalog,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failed_save(result: ExposureMeasurement) -> None:
        raise SQLAlchemyError("disk failure")

    monkeypatch.setattr(catalog.results, "save", failed_save)
    response = client.post(_path(catalog), headers=HEADERS)
    assert response.status_code == 503
    assert "salvare" in caplog.text
    assert catalog.results.get(catalog.shot.shot_id) is None


def test_saved_page_does_not_silently_hide_measurement_read_failures(
    client: TestClient,
    catalog: ExposureCatalog,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failed_get_many(shot_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, ExposureMeasurement]:
        raise SQLAlchemyError("database offline")

    monkeypatch.setattr(catalog.results, "get_many", failed_get_many)
    response = client.get(
        f"/api/v1/photos/sessions/{catalog.session.session_id}/shots", headers=HEADERS
    )
    assert response.status_code == 503
    assert "misure di esposizione" in response.json()["detail"]
    assert "misure di esposizione" in caplog.text


def test_read_failure_is_logged_and_reported(
    client: TestClient,
    catalog: ExposureCatalog,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failed_get(shot_id: uuid.UUID) -> ExposureMeasurement | None:
        raise SQLAlchemyError("database offline")

    monkeypatch.setattr(catalog.results, "get", failed_get)
    response = client.get(_path(catalog), headers=HEADERS)
    assert response.status_code == 503
    assert "leggere" in caplog.text


def test_unconfigured_exposure_does_not_prevent_core_startup(catalog: ExposureCatalog) -> None:
    configuration = ConfigurationService(SqlSettingsRepository(catalog.db), EnvSecretStore({}))
    with TestClient(create_app(configuration, TOKEN)) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.post(_path(catalog), headers=HEADERS).status_code == 503
        assert client.get(_path(catalog), headers=HEADERS).status_code == 503


def test_results_persist_across_app_restart(catalog: ExposureCatalog, client: TestClient) -> None:
    saved = client.post(_path(catalog), headers=HEADERS).json()
    configuration = ConfigurationService(SqlSettingsRepository(catalog.db), EnvSecretStore({}))
    with TestClient(
        create_app(configuration, TOKEN, exposure_service=catalog.service)
    ) as restarted:
        assert restarted.get(_path(catalog), headers=HEADERS).json() == saved
        assert restarted.post(_path(catalog), headers=HEADERS).json() == saved
    assert catalog.analyzer.calls == 1


def test_exposure_is_independent_of_exiftool(client: TestClient, catalog: ExposureCatalog) -> None:
    catalog.shot.files[0].path.unlink()
    assert client.post(_path(catalog), headers=HEADERS).status_code == 200
    assert client.get("/api/v1/health").status_code == 200
    assert catalog.sessions.get(catalog.session.session_id) == catalog.session
    assert not catalog.shot.files[0].path.exists()
