import json
import uuid
from pathlib import Path

import pytest

from shotkeepr.core.__main__ import main

from ..quality.conftest import ExposureCatalog
from .conftest import shot


def test_cli_grouping_persists_is_idempotent_and_is_visible_in_show(
    catalog: ExposureCatalog, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog.shots.add_many(
        [shot(catalog.session.session_id, 0), shot(catalog.session.session_id, 1)]
    )
    args = ["photos", "group", str(catalog.session.session_id), "--data-dir", str(catalog.data)]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["gap_seconds"] == 2
    assert result["groups"][0]["shots"] == 2
    assert result["ungrouped_shots"] == 1
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert (
        main(["photos", "show", str(catalog.session.session_id), "--data-dir", str(catalog.data)])
        == 0
    )
    shown = json.loads(capsys.readouterr().out)
    assert shown["grouping"] == result
    assert shown["status"] == "IMPORTED"
    assert sum(item["group_id"] is not None for item in shown["shots"]) == 2
    assert main([*args, "--gap-seconds", "0.5"]) == 0
    changed = json.loads(capsys.readouterr().out)
    assert changed["groups"] == [] and changed["ungrouped_shots"] == 3


@pytest.mark.parametrize("gap", ["0", "-1", "60.01", "nan", "inf"])
def test_invalid_cli_gap_has_no_success_output(
    catalog: ExposureCatalog, capsys: pytest.CaptureFixture[str], gap: str
) -> None:
    assert (
        main(
            [
                "photos",
                "group",
                str(catalog.session.session_id),
                "--data-dir",
                str(catalog.data),
                "--gap-seconds",
                gap,
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert not captured.out
    assert "Intervallo raffica" in captured.err


def test_missing_catalog_is_not_created(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "absent"
    assert main(["photos", "group", str(uuid.uuid4()), "--data-dir", str(missing)]) == 1
    assert "catalogo non presente" in capsys.readouterr().err
    assert not missing.exists()
