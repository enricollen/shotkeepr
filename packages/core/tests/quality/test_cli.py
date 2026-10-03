import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shotkeepr.core.__main__ import main
from shotkeepr.core.domain.catalog import Shot

from .conftest import ExposureCatalog


def test_cli_exposure_persists_reuses_and_shows_partial_measurements(
    catalog: ExposureCatalog, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["photos", "exposure", str(catalog.session.session_id), "--data-dir", str(catalog.data)]
    assert main(args) == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert "Esposizione anteprima: 1/1 scatti" in captured.err
    assert summary["status"] == "IMPORTED"
    assert summary["full_analysis_performed"] is False
    assert summary["exposure"][0]["score"] == 100
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == summary
    assert (
        main(["photos", "show", str(catalog.session.session_id), "--data-dir", str(catalog.data)])
        == 0
    )
    shown = json.loads(capsys.readouterr().out)
    assert shown["shots"][0]["exposure"] == summary["exposure"][0]
    assert catalog.sessions.get(catalog.session.session_id) == catalog.session


def test_cli_exposure_reports_missing_preview_without_a_success_result(
    catalog: ExposureCatalog, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog.preview.unlink()
    assert (
        main(
            ["photos", "exposure", str(catalog.session.session_id), "--data-dir", str(catalog.data)]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "anteprima" in captured.err
    assert not captured.out
    assert catalog.results.get(catalog.shot.shot_id) is None


def test_cli_exposure_rejects_missing_catalog_without_creating_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "absent"
    assert main(["photos", "exposure", str(uuid.uuid4()), "--data-dir", str(data)]) == 1
    assert "catalogo non presente" in capsys.readouterr().err
    assert not data.exists()


def test_cli_exposure_rejects_unknown_session(
    catalog: ExposureCatalog, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["photos", "exposure", str(uuid.uuid4()), "--data-dir", str(catalog.data)]) == 1
    assert "sessione non presente" in capsys.readouterr().err


def test_cli_failure_preserves_completed_shots_without_a_partial_success_summary(
    catalog: ExposureCatalog, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = Shot(
        catalog.session.session_id,
        "missing-preview",
        capture_time=datetime(2026, 10, 2, tzinfo=UTC),
    )
    catalog.shots.add_many([missing])
    args = ["photos", "exposure", str(catalog.session.session_id), "--data-dir", str(catalog.data)]
    assert main(args) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert "Esposizione anteprima: 1/2 scatti" in captured.err
    assert "file immagine" in captured.err
    saved = catalog.results.get(catalog.shot.shot_id)
    assert saved is not None
    assert catalog.results.get(missing.shot_id) is None
    assert main(args) == 1
    assert catalog.results.get(catalog.shot.shot_id) == saved
    assert catalog.sessions.get(catalog.session.session_id) == catalog.session
