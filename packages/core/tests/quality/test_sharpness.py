import io
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFilter
from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.__main__ import main
from shotkeepr.core.adapters.persistence.sharpness import SqlSharpnessRepository
from shotkeepr.core.adapters.quality.factory import sharpness_service
from shotkeepr.core.adapters.quality.preview import MAX_PREVIEW_BYTES
from shotkeepr.core.adapters.quality.sharpness import PillowSharpnessAnalyzer
from shotkeepr.core.domain.catalog import Shot
from shotkeepr.core.domain.quality.sharpness import (
    SharpnessError,
    SharpnessMeasurement,
    SharpnessMetrics,
    SharpnessShotNotFoundError,
)

from .conftest import ExposureCatalog


def _jpeg(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=100, subsampling=0)
    return output.getvalue()


def test_uniform_images_have_zero_detail_not_an_invented_quality_score() -> None:
    analyzer = PillowSharpnessAnalyzer()
    for value in (0, 128, 255):
        with Image.new("RGB", (64, 32), (value, value, value)) as image:
            result = analyzer.measure(_jpeg(image))
        assert result.width == 64 and result.height == 32
        assert result.laplacian_variance == pytest.approx(0)
        assert result.gradient_energy == pytest.approx(0)


def test_synthetic_detail_exceeds_its_blurred_version_and_is_reproducible() -> None:
    pixels = ((np.indices((64, 64)).sum(axis=0) % 2) * 255).astype(np.uint8)
    analyzer = PillowSharpnessAnalyzer()
    with Image.fromarray(pixels) as image, image.filter(ImageFilter.GaussianBlur(2)) as blurred:
        content = _jpeg(image)
        sharp = analyzer.measure(content)
        soft = analyzer.measure(_jpeg(blurred))
    assert sharp.laplacian_variance > soft.laplacian_variance
    assert sharp.gradient_energy > soft.gradient_energy
    assert analyzer.measure(content) == sharp


@pytest.mark.parametrize("content", [b"", b"bad jpeg", b"x" * (MAX_PREVIEW_BYTES + 1)])
def test_invalid_content_is_rejected(content: bytes) -> None:
    with pytest.raises(SharpnessError):
        PillowSharpnessAnalyzer().measure(content)


@pytest.mark.parametrize("size", [(2, 20), (20, 2), (513, 32)])
def test_unusable_preview_dimensions_are_rejected(size: tuple[int, int]) -> None:
    with Image.new("RGB", size, "gray") as image:
        content = _jpeg(image)
    with pytest.raises(SharpnessError):
        PillowSharpnessAnalyzer().measure(content)


def test_a_png_is_not_silently_treated_as_a_jpeg() -> None:
    output = io.BytesIO()
    with Image.new("RGB", (32, 32), "gray") as image:
        image.save(output, format="PNG")
    with pytest.raises(SharpnessError):
        PillowSharpnessAnalyzer().measure(output.getvalue())


@pytest.mark.parametrize(
    "values",
    [
        (2, 32, 0, 0),
        (32, 32, float("nan"), 0),
        (32, 32, -1, 0),
        (32, 32, 17, 0),
        (32, 32, 0, float("inf")),
        (32, 32, 0, 2),
    ],
)
def test_domain_rejects_invalid_metrics(values: tuple[int, int, float, float]) -> None:
    with pytest.raises(ValueError):
        SharpnessMetrics(*values)


def test_invalid_provenance_is_rejected() -> None:
    result = SharpnessMeasurement(
        uuid.uuid4(),
        "a" * 64,
        "b" * 64,
        "v1",
        datetime.now(UTC),
        SharpnessMetrics(32, 32, 0, 0),
    )
    for changes in (
        {"preview_sha256": "invalid"},
        {"source_fingerprint": "z" * 64},
        {"analyzer_version": " "},
        {"measured_at": datetime(2026, 10, 3)},
    ):
        with pytest.raises(ValueError):
            replace(result, **changes)


def test_measurements_persist_reuse_and_invalidate_changed_previews(
    catalog: ExposureCatalog,
) -> None:
    service = sharpness_service(catalog.db, catalog.data)
    original = catalog.shot.files[0].path.read_bytes()
    timestamp = catalog.shot.files[0].path.stat().st_mtime_ns
    saved = service.measure(catalog.shot.shot_id)
    assert service.measure(catalog.shot.shot_id) == saved
    assert sharpness_service(catalog.db, catalog.data).results.get(catalog.shot.shot_id) == saved
    with Image.new("RGB", (32, 32), "black") as image:
        catalog.preview.write_bytes(_jpeg(image))
    changed = service.measure(catalog.shot.shot_id)
    assert changed.preview_sha256 != saved.preview_sha256
    assert changed.measured_at >= saved.measured_at
    assert changed.metrics.width == changed.metrics.height == 32
    assert catalog.sessions.get(catalog.session.session_id) == catalog.session
    assert catalog.results.get(catalog.shot.shot_id) is None
    assert catalog.shot.files[0].path.read_bytes() == original
    assert catalog.shot.files[0].path.stat().st_mtime_ns == timestamp


def test_method_changes_recompute_and_bad_previews_preserve_previous_results(
    catalog: ExposureCatalog,
) -> None:
    service = sharpness_service(catalog.db, catalog.data)
    saved = service.measure(catalog.shot.shot_id)
    service._analyzer.version = "preview-luma-laplacian-v2-test"
    updated = service.measure(catalog.shot.shot_id)
    assert updated.analyzer_version != saved.analyzer_version
    catalog.preview.write_bytes(b"corrupt")
    with pytest.raises(SharpnessError):
        service.measure(catalog.shot.shot_id)
    assert service.results.get(catalog.shot.shot_id) == updated


def test_unknown_shot_and_missing_preview_do_not_report_success(catalog: ExposureCatalog) -> None:
    service = sharpness_service(catalog.db, catalog.data)
    with pytest.raises(SharpnessShotNotFoundError):
        service.measure(uuid.uuid4())
    catalog.preview.unlink()
    with pytest.raises(SharpnessError, match="non accessibile"):
        service.measure(catalog.shot.shot_id)
    assert service.results.get(catalog.shot.shot_id) is None


def test_sql_failures_propagate_without_a_false_success(
    catalog: ExposureCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = sharpness_service(catalog.db, catalog.data)

    def failed(result: SharpnessMeasurement) -> None:
        raise SQLAlchemyError("disk failure")

    monkeypatch.setattr(service.results, "save", failed)
    with pytest.raises(SQLAlchemyError):
        service.measure(catalog.shot.shot_id)
    assert SqlSharpnessRepository(catalog.db).get(catalog.shot.shot_id) is None


def test_cli_results_are_persisted_and_visible_offline(
    catalog: ExposureCatalog, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog.shot.files[0].path.unlink()
    args = ["photos", "sharpness", str(catalog.session.session_id), "--data-dir", str(catalog.data)]
    assert main(args) == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert "Nitidezza anteprima: 1/1 scatti" in captured.err
    assert summary["full_analysis_performed"] is False
    assert summary["status"] == "IMPORTED"
    assert "score" not in summary["sharpness"][0]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == summary
    assert (
        main(["photos", "show", str(catalog.session.session_id), "--data-dir", str(catalog.data)])
        == 0
    )
    shown = json.loads(capsys.readouterr().out)
    assert shown["shots"][0]["sharpness"] == summary["sharpness"][0]
    assert shown["shots"][0]["exposure"] is None


def test_cli_failure_retains_completed_shots_without_a_success_summary(
    catalog: ExposureCatalog, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = Shot(catalog.session.session_id, "missing", capture_time=datetime.now(UTC))
    catalog.shots.add_many([missing])
    assert (
        main(
            [
                "photos",
                "sharpness",
                str(catalog.session.session_id),
                "--data-dir",
                str(catalog.data),
            ]
        )
        == 1
    )
    failed = capsys.readouterr()
    assert not failed.out
    assert "Nitidezza anteprima: 1/2 scatti" in failed.err
    assert "file immagine" in failed.err
    assert SqlSharpnessRepository(catalog.db).get(catalog.shot.shot_id) is not None
    assert SqlSharpnessRepository(catalog.db).get(missing.shot_id) is None


def test_missing_catalog_is_not_created(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "absent"
    assert main(["photos", "sharpness", str(uuid.uuid4()), "--data-dir", str(missing)]) == 1
    assert "catalogo non presente" in capsys.readouterr().err
    assert not missing.exists()
