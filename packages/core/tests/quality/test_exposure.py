import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from alembic import command
from PIL import Image
from sqlalchemy import delete, inspect
from sqlalchemy.exc import IntegrityError

from shotkeepr.core.adapters.persistence.migrate import alembic_config, upgrade_to_head
from shotkeepr.core.adapters.persistence.models import ShotRow
from shotkeepr.core.adapters.quality.exposure import (
    MAX_PREVIEW_BYTES,
    PillowExposureAnalyzer,
)
from shotkeepr.core.domain.catalog import FileKind, ImageFile, Shot
from shotkeepr.core.domain.quality.exposure import (
    ExposureError,
    ExposureMeasurement,
    ExposureMetrics,
    ExposureShotNotFoundError,
)

from .conftest import ExposureCatalog


def _image(
    color: tuple[int, int, int], *, size: tuple[int, int] = (32, 16), format: str = "JPEG"
) -> bytes:
    output = io.BytesIO()
    with Image.new("RGB", size, color) as image:
        image.save(output, format=format, quality=100, subsampling=0)
    return output.getvalue()


@pytest.mark.parametrize(
    ("color", "highlights", "shadows", "score", "luma"),
    [
        ((0, 0, 0), 0, 1, 0, 0),
        ((255, 255, 255), 1, 0, 0, 1),
        ((128, 128, 128), 0, 0, 100, 128 / 255),
        ((255, 0, 0), 1, 0, 0, 0.2126),
    ],
)
def test_uniform_images_and_saturation_of_a_single_channel(
    color: tuple[int, int, int], highlights: float, shadows: float, score: float, luma: float
) -> None:
    result = PillowExposureAnalyzer().measure(_image(color))
    assert result.width == 32 and result.height == 16
    assert result.highlights_fraction == highlights
    assert result.shadows_fraction == shadows
    assert result.score == score
    assert result.mean_luma == pytest.approx(luma, abs=0.002)


@pytest.mark.parametrize(
    ("value", "highlights", "shadows"),
    [(4, 0, 1), (5, 0, 1), (6, 0, 0), (249, 0, 0), (250, 1, 0), (251, 1, 0)],
)
def test_clipping_thresholds_are_inclusive(value: int, highlights: float, shadows: float) -> None:
    result = PillowExposureAnalyzer().measure(_image((value, value, value)))
    assert result.highlights_fraction == highlights
    assert result.shadows_fraction == shadows


def test_dark_pixels_with_a_nonclosed_channel_are_not_counted_as_closed_shadows() -> None:
    result = PillowExposureAnalyzer().measure(_image((0, 0, 16)))
    assert result.mean_luma < 0.01
    assert result.shadows_fraction == 0


def test_maximum_supported_preview_is_accepted_and_reproducible() -> None:
    content = _image((128, 128, 128), size=(512, 512))
    analyzer = PillowExposureAnalyzer()
    result = analyzer.measure(content)
    assert result.width == result.height == 512
    assert result.score == 100
    assert analyzer.measure(content) == result


def test_mixed_pixels_use_pixel_fractions_not_channel_counts() -> None:
    output = io.BytesIO()
    with Image.new("RGB", (32, 16), (128, 128, 128)) as image:
        image.paste((255, 255, 255), (0, 0, 8, 16))
        image.paste((0, 0, 0), (8, 0, 16, 16))
        image.save(output, format="JPEG", quality=100, subsampling=0)
    result = PillowExposureAnalyzer().measure(output.getvalue())
    assert result.highlights_fraction == 0.25
    assert result.shadows_fraction == 0.25
    assert result.score == 50


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not a jpeg",
        b"x" * (MAX_PREVIEW_BYTES + 1),
        _image((128, 128, 128), format="PNG"),
        _image((128, 128, 128), size=(513, 1)),
    ],
)
def test_invalid_or_unbounded_previews_fail_explicitly(content: bytes) -> None:
    with pytest.raises(ExposureError):
        PillowExposureAnalyzer().measure(content)


@pytest.mark.parametrize(
    "values",
    [
        (0, 1, 0.5, 0, 0),
        (1, 0, 0.5, 0, 0),
        (1, 1, float("nan"), 0, 0),
        (1, 1, 0.5, float("inf"), 0),
        (1, 1, 0.5, 0.6, 0.6),
        (1, 1, 0.5, -0.1, 0),
    ],
)
def test_domain_rejects_invalid_metrics(values: tuple[int, int, float, float, float]) -> None:
    with pytest.raises(ValueError):
        ExposureMetrics(*values)


def test_measurement_rejects_invalid_provenance() -> None:
    result = ExposureMeasurement(
        uuid.uuid4(), "a" * 64, "b" * 64, "v1", datetime.now(UTC), ExposureMetrics(1, 1, 0.5, 0, 0)
    )
    for changes in (
        {"source_fingerprint": "invalid"},
        {"preview_sha256": "z" * 64},
        {"analyzer_version": " "},
        {"measured_at": datetime(2026, 10, 2)},
    ):
        with pytest.raises(ValueError):
            replace(result, **changes)


def test_service_reuses_saved_measurement_without_full_analysis(catalog: ExposureCatalog) -> None:
    original = catalog.shot.files[0].path.read_bytes()
    first = catalog.service.measure(catalog.shot.shot_id)
    assert first.metrics.score == 100
    assert catalog.service.measure(catalog.shot.shot_id) == first
    assert catalog.analyzer.calls == 1
    assert catalog.results.get(catalog.shot.shot_id) == first
    assert catalog.sessions.get(catalog.session.session_id) == catalog.session
    assert catalog.shot.files[0].path.read_bytes() == original
    assert catalog.results.get_many([catalog.shot.shot_id, uuid.uuid4()]) == {first.shot_id: first}
    assert catalog.results.get_many([]) == {}


def test_version_and_preview_content_changes_invalidate_measurement(
    catalog: ExposureCatalog,
) -> None:
    first = catalog.service.measure(catalog.shot.shot_id)
    catalog.analyzer.version = "preview-rgb-exposure-v2"
    second = catalog.service.measure(catalog.shot.shot_id)
    assert second.analyzer_version != first.analyzer_version
    assert catalog.analyzer.calls == 2
    catalog.preview.write_bytes(_image((255, 255, 255)))
    third = catalog.service.measure(catalog.shot.shot_id)
    assert third.metrics.score == 0
    assert third.preview_sha256 != second.preview_sha256
    assert catalog.analyzer.calls == 3
    assert catalog.results.get(catalog.shot.shot_id) == third


@pytest.mark.parametrize("failure", ["missing", "corrupt", "oversized"])
def test_unavailable_preview_never_reuses_a_success_shaped_result(
    catalog: ExposureCatalog, failure: str
) -> None:
    saved = catalog.service.measure(catalog.shot.shot_id)
    if failure == "missing":
        catalog.preview.unlink()
    elif failure == "corrupt":
        catalog.preview.write_bytes(b"corrupt")
    else:
        catalog.preview.write_bytes(b"x" * (MAX_PREVIEW_BYTES + 1))
    with pytest.raises(ExposureError):
        catalog.service.measure(catalog.shot.shot_id)
    assert catalog.results.get(catalog.shot.shot_id) == saved
    assert catalog.sessions.get(catalog.session.session_id) == catalog.session


def test_measurement_requires_no_originals_online(catalog: ExposureCatalog) -> None:
    catalog.shot.files[0].path.unlink()
    result = catalog.service.measure(catalog.shot.shot_id)
    assert result.metrics.score == 100


def test_raw_jpeg_pair_uses_same_preferred_preview_as_thumbnail(catalog: ExposureCatalog) -> None:
    raw = ImageFile(catalog.session.source_folder / "photo.raw", "DNG", FileKind.RAW, 10, "a" * 64)
    pair = Shot(catalog.session.session_id, "pair", files=[raw, catalog.shot.files[0]])
    pair.files[1] = replace(pair.files[1], file_id=uuid.uuid4())
    catalog.shots.add_many([pair])
    assert pair.preview_file == pair.files[1]
    result = catalog.service.measure(pair.shot_id)
    assert result.source_fingerprint == pair.files[1].fingerprint


def test_missing_empty_or_unsafe_shot_cannot_be_measured(catalog: ExposureCatalog) -> None:
    with pytest.raises(ExposureShotNotFoundError):
        catalog.service.measure(uuid.uuid4())
    empty = Shot(catalog.session.session_id, "empty")
    invalid = Shot(
        catalog.session.session_id,
        "invalid",
        files=[ImageFile(catalog.data / "invalid", "JPEG", FileKind.STANDARD, 1, "invalid")],
    )
    catalog.shots.add_many([empty, invalid])
    for shot in (empty, invalid):
        with pytest.raises(ExposureError):
            catalog.service.measure(shot.shot_id)
        assert catalog.results.get(shot.shot_id) is None


def test_concurrent_requests_publish_one_valid_measurement(catalog: ExposureCatalog) -> None:
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(catalog.service.measure, [catalog.shot.shot_id] * 8))
    assert all(result.metrics == results[0].metrics for result in results)
    saved = catalog.results.get(catalog.shot.shot_id)
    assert saved in results
    assert len(catalog.results.get_many([catalog.shot.shot_id])) == 1


def test_repository_enforces_shot_foreign_key_and_deletion_cascades(
    catalog: ExposureCatalog,
) -> None:
    result = catalog.service.measure(catalog.shot.shot_id)
    with pytest.raises(IntegrityError):
        catalog.results.save(replace(result, shot_id=uuid.uuid4()))
    assert catalog.results.get(result.shot_id) == result
    with catalog.db.transaction() as tx:
        tx.execute(delete(ShotRow).where(ShotRow.id == result.shot_id))
    assert catalog.results.get(result.shot_id) is None


def test_upgrade_and_downgrade_preserve_existing_catalog(catalog: ExposureCatalog) -> None:
    result = catalog.service.measure(catalog.shot.shot_id)
    command.downgrade(alembic_config(catalog.db.url), "0002")
    assert "exposure_measurements" not in inspect(catalog.db.engine).get_table_names()
    assert catalog.shots.get(catalog.shot.shot_id) == catalog.shot
    upgrade_to_head(catalog.db.url)
    assert catalog.results.get(result.shot_id) is None
    assert catalog.sessions.get(catalog.session.session_id) == catalog.session
    assert catalog.service.measure(catalog.shot.shot_id).metrics == result.metrics
