import uuid
from collections.abc import Iterator, Sequence

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.adapters.persistence.settings import SqlSettingsRepository
from shotkeepr.core.adapters.review.factory import review_service
from shotkeepr.core.adapters.review.xmp import ExifToolXmpWriter
from shotkeepr.core.adapters.secrets.stores import EnvSecretStore
from shotkeepr.core.api.app import create_app
from shotkeepr.core.api.import_jobs import ImportJobs
from shotkeepr.core.application.configuration import ConfigurationService
from shotkeepr.core.application.ingestion import PhotoImportService
from shotkeepr.core.domain.catalog import SessionStatus
from shotkeepr.core.domain.catalog.review import ShotReview

from ..quality.conftest import ExposureCatalog

TOKEN = "review-test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(catalog: ExposureCatalog) -> Iterator[TestClient]:
    def unused_import() -> PhotoImportService:
        pytest.fail("review must never import photographs")

    jobs = ImportJobs(unused_import, catalog.sessions, catalog.shots, catalog.previews)
    configuration = ConfigurationService(SqlSettingsRepository(catalog.db), EnvSecretStore({}))
    app = create_app(
        configuration,
        TOKEN,
        import_jobs=jobs,
        exposure_service=catalog.service,
        review_service=review_service(catalog.db, catalog.data),
    )
    with TestClient(app) as client:
        yield client


def _path(catalog: ExposureCatalog) -> str:
    return f"/api/v1/photos/shots/{catalog.shot.shot_id}"


def test_review_and_export_require_authentication(
    client: TestClient, catalog: ExposureCatalog
) -> None:
    root = _path(catalog)
    assert client.get(root + "/review").status_code == 401
    assert client.put(root + "/review", json={"status": "KEEP"}).status_code == 401
    assert (
        client.post(root + "/xmp", json={"confirm": True, "expected_status": "KEEP"}).status_code
        == 401
    )
    assert not catalog.shot.files[0].path.with_suffix(".xmp").exists()


def test_saved_review_is_visible_in_catalog_pages_without_analysis(
    client: TestClient, catalog: ExposureCatalog
) -> None:
    root = _path(catalog)
    assert client.get(root + "/review", headers=HEADERS).json()["status"] == "REVIEW"
    saved = client.put(root + "/review", headers=HEADERS, json={"status": "KEEP"})
    assert saved.status_code == 200
    assert saved.json()["updated_at"]
    assert (
        client.put(root + "/review", headers=HEADERS, json={"status": "KEEP"}).json()
        == saved.json()
    )
    assert client.get(root + "/review", headers=HEADERS).json() == saved.json()
    page = client.get(
        f"/api/v1/photos/sessions/{catalog.session.session_id}/shots",
        headers=HEADERS,
    ).json()
    assert page["items"][0]["review"] == saved.json()
    assert page["items"][0]["exposure"] is None
    assert catalog.sessions.get(catalog.session.session_id) == catalog.session
    assert not catalog.shot.files[0].path.with_suffix(".xmp").exists()


def test_invalid_or_unconfirmed_requests_never_write(
    client: TestClient, catalog: ExposureCatalog
) -> None:
    root = _path(catalog)
    assert client.put(root + "/review", headers=HEADERS, json={"status": "AUTO"}).status_code == 422
    for body in (
        {},
        {"expected_status": "REVIEW"},
        {"confirm": False, "expected_status": "REVIEW"},
    ):
        assert client.post(root + "/xmp", headers=HEADERS, json=body).status_code == 422
    assert not catalog.shot.files[0].path.with_suffix(".xmp").exists()


def test_explicit_export_checks_the_saved_status_and_creates_only_sidecars(
    client: TestClient, catalog: ExposureCatalog, exiftool: str
) -> None:
    root = _path(catalog)
    original = catalog.shot.files[0].path.read_bytes()
    client.put(root + "/review", headers=HEADERS, json={"status": "KEEP"})
    assert (
        client.post(
            root + "/xmp",
            headers=HEADERS,
            json={"confirm": True, "expected_status": "REJECT"},
        ).status_code
        == 409
    )
    result = client.post(
        root + "/xmp",
        headers=HEADERS,
        json={"confirm": True, "expected_status": "KEEP"},
    )
    assert result.status_code == 200
    assert result.json()["status"] == "KEEP"
    assert result.json()["paths"] == [str(catalog.shot.files[0].path.with_suffix(".xmp"))]
    assert catalog.shot.files[0].path.read_bytes() == original


def test_missing_exiftool_does_not_block_review_or_health(
    client: TestClient, catalog: ExposureCatalog
) -> None:
    client.app.state.review_service.writer = ExifToolXmpWriter(
        catalog.data / "locks",
        executable="missing-shotkeepr-exiftool",
    )
    root = _path(catalog)
    assert client.put(root + "/review", headers=HEADERS, json={"status": "KEEP"}).status_code == 200
    failed = client.post(
        root + "/xmp", headers=HEADERS, json={"confirm": True, "expected_status": "KEEP"}
    )
    assert failed.status_code == 503
    assert "ExifTool" in failed.json()["detail"]
    assert client.get("/api/v1/health").status_code == 200


def test_unknown_or_busy_shots_are_rejected(client: TestClient, catalog: ExposureCatalog) -> None:
    path = f"/api/v1/photos/shots/{uuid.uuid4()}/review"
    assert client.get(path, headers=HEADERS).status_code == 404
    assert client.put(path, headers=HEADERS, json={"status": "KEEP"}).status_code == 404
    catalog.session.status = SessionStatus.ANALYZING
    catalog.sessions.update(catalog.session)
    assert (
        client.put(_path(catalog) + "/review", headers=HEADERS, json={"status": "KEEP"}).status_code
        == 409
    )


def test_database_errors_are_reported_not_hidden(
    client: TestClient,
    catalog: ExposureCatalog,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failed_get_many(shot_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, ShotReview]:
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(client.app.state.review_service.reviews, "get_many", failed_get_many)
    response = client.get(
        f"/api/v1/photos/sessions/{catalog.session.session_id}/shots", headers=HEADERS
    )
    assert response.status_code == 503
    assert "revisioni" in response.json()["detail"]
    assert "revisioni" in caplog.text


def test_unconfigured_review_is_explicit(catalog: ExposureCatalog) -> None:
    configuration = ConfigurationService(SqlSettingsRepository(catalog.db), EnvSecretStore({}))
    with TestClient(create_app(configuration, TOKEN)) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get(_path(catalog) + "/review", headers=HEADERS).status_code == 503
