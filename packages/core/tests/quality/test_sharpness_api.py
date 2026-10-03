import uuid
from collections.abc import Iterator, Sequence

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.adapters.persistence.settings import SqlSettingsRepository
from shotkeepr.core.adapters.quality.factory import sharpness_service
from shotkeepr.core.adapters.secrets.stores import EnvSecretStore
from shotkeepr.core.api.app import create_app
from shotkeepr.core.api.import_jobs import ImportJobs
from shotkeepr.core.application.configuration import ConfigurationService
from shotkeepr.core.application.ingestion import PhotoImportService
from shotkeepr.core.domain.quality.sharpness import SharpnessMeasurement

from .conftest import ExposureCatalog

TOKEN = "test-sharpness-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(catalog: ExposureCatalog) -> Iterator[TestClient]:
    def unused_import() -> PhotoImportService:
        pytest.fail("measuring sharpness must not start an import")

    jobs = ImportJobs(unused_import, catalog.sessions, catalog.shots, catalog.previews)
    configuration = ConfigurationService(SqlSettingsRepository(catalog.db), EnvSecretStore({}))
    with TestClient(
        create_app(
            configuration,
            TOKEN,
            import_jobs=jobs,
            exposure_service=catalog.service,
            sharpness_service=sharpness_service(catalog.db, catalog.data),
        )
    ) as client:
        yield client


def _path(catalog: ExposureCatalog) -> str:
    return f"/api/v1/photos/shots/{catalog.shot.shot_id}/sharpness"


def test_explicit_measurement_requires_authentication_and_is_persisted(
    client: TestClient, catalog: ExposureCatalog
) -> None:
    path = _path(catalog)
    assert client.get(path).status_code == 401
    assert client.post(path).status_code == 401
    assert client.get(path, headers=HEADERS).status_code == 404
    exposure = catalog.service.measure(catalog.shot.shot_id)
    response = client.post(path, headers=HEADERS)
    assert response.status_code == 200
    result = response.json()
    assert result["laplacian_variance"] == 0
    assert result["gradient_energy"] == 0
    assert result["width"] == 64 and result["height"] == 32
    assert result["analyzer_version"] == "preview-luma-laplacian-v1"
    assert "score" not in result
    assert client.post(path, headers=HEADERS).json() == result
    assert client.get(path, headers=HEADERS).json() == result
    page = client.get(
        f"/api/v1/photos/sessions/{catalog.session.session_id}/shots", headers=HEADERS
    ).json()
    assert page["items"][0]["sharpness"] == result
    assert page["items"][0]["exposure"]["measured_at"] == exposure.measured_at.isoformat().replace(
        "+00:00", "Z"
    )
    assert catalog.results.get(catalog.shot.shot_id) == exposure
    assert catalog.sessions.get(catalog.session.session_id) == catalog.session
    schema = client.get("/openapi.json").json()
    assert (
        schema["paths"]["/api/v1/photos/shots/{shot_id}/sharpness"]["post"]["operationId"]
        == "measure_photo_sharpness"
    )


def test_catalog_reads_do_not_measure_automatically(
    client: TestClient, catalog: ExposureCatalog
) -> None:
    response = client.get(
        f"/api/v1/photos/sessions/{catalog.session.session_id}/shots", headers=HEADERS
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["sharpness"] is None
    assert client.app.state.sharpness_service.results.get(catalog.shot.shot_id) is None


@pytest.mark.parametrize("method", ["get", "post"])
def test_unknown_shot_does_not_report_success(client: TestClient, method: str) -> None:
    assert (
        client.request(
            method, f"/api/v1/photos/shots/{uuid.uuid4()}/sharpness", headers=HEADERS
        ).status_code
        == 404
    )


@pytest.mark.parametrize("failure", ["missing", "corrupt"])
def test_bad_preview_keeps_the_previous_result_readable(
    client: TestClient, catalog: ExposureCatalog, failure: str
) -> None:
    saved = client.post(_path(catalog), headers=HEADERS).json()
    if failure == "missing":
        catalog.preview.unlink()
    else:
        catalog.preview.write_bytes(b"not a jpeg")
    failed = client.post(_path(catalog), headers=HEADERS)
    assert failed.status_code == 409
    assert "anteprima" in failed.json()["detail"]
    assert client.get(_path(catalog), headers=HEADERS).json() == saved


def test_sql_write_failure_is_logged_and_never_a_success(
    client: TestClient,
    catalog: ExposureCatalog,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failed_save(result: SharpnessMeasurement) -> None:
        raise SQLAlchemyError("disk failure")

    monkeypatch.setattr(client.app.state.sharpness_service.results, "save", failed_save)
    response = client.post(_path(catalog), headers=HEADERS)
    assert response.status_code == 503
    assert "salvare" in caplog.text
    assert client.app.state.sharpness_service.results.get(catalog.shot.shot_id) is None


@pytest.mark.parametrize("route", ["measurement", "page"])
def test_sql_read_errors_are_not_hidden_as_missing_measurements(
    client: TestClient,
    catalog: ExposureCatalog,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    route: str,
) -> None:
    def failed_get(shot_id: uuid.UUID) -> SharpnessMeasurement | None:
        raise SQLAlchemyError("database unavailable")

    def failed_many(shot_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, SharpnessMeasurement]:
        raise SQLAlchemyError("database unavailable")

    results = client.app.state.sharpness_service.results
    monkeypatch.setattr(results, "get", failed_get)
    monkeypatch.setattr(results, "get_many", failed_many)
    path = (
        _path(catalog)
        if route == "measurement"
        else f"/api/v1/photos/sessions/{catalog.session.session_id}/shots"
    )
    failed = client.get(path, headers=HEADERS)
    assert failed.status_code == 503
    assert "nitidezza" in caplog.text
    assert "nitidezza" in failed.json()["detail"]


def test_restart_and_offline_originals_do_not_lose_measurements(
    client: TestClient, catalog: ExposureCatalog
) -> None:
    saved = client.post(_path(catalog), headers=HEADERS).json()
    catalog.shot.files[0].path.unlink()
    configuration = ConfigurationService(SqlSettingsRepository(catalog.db), EnvSecretStore({}))
    with TestClient(
        create_app(
            configuration,
            TOKEN,
            sharpness_service=sharpness_service(catalog.db, catalog.data),
        )
    ) as restarted:
        assert restarted.get(_path(catalog), headers=HEADERS).json() == saved
        assert restarted.post(_path(catalog), headers=HEADERS).json() == saved


def test_unconfigured_measurement_does_not_block_health(catalog: ExposureCatalog) -> None:
    configuration = ConfigurationService(SqlSettingsRepository(catalog.db), EnvSecretStore({}))
    with TestClient(create_app(configuration, TOKEN)) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.post(_path(catalog), headers=HEADERS).status_code == 503
        assert client.get(_path(catalog), headers=HEADERS).status_code == 503
