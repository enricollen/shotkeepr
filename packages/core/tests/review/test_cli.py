import json
import uuid
from pathlib import Path

import pytest

from shotkeepr.core.__main__ import main

from ..quality.conftest import ExposureCatalog


def test_cli_review_is_persisted_and_visible_in_show(
    catalog: ExposureCatalog, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["photos", "review", str(catalog.shot.shot_id), "KEEP", "--data-dir", str(catalog.data)]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "KEEP"
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert (
        main(["photos", "show", str(catalog.session.session_id), "--data-dir", str(catalog.data)])
        == 0
    )
    shown = json.loads(capsys.readouterr().out)
    assert shown["shots"][0]["review"] == result
    assert shown["status"] == "IMPORTED"


def test_cli_export_is_dry_run_by_default_and_write_is_explicit(
    catalog: ExposureCatalog, capsys: pytest.CaptureFixture[str], exiftool: str
) -> None:
    source = catalog.shot.files[0].path
    before = source.read_bytes()
    args = [
        "photos",
        "export-xmp",
        str(catalog.session.session_id),
        "--data-dir",
        str(catalog.data),
    ]
    assert main(args) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["written"] is False
    assert planned["sidecars"][0]["status"] == "REVIEW"
    assert planned["sidecars"][0]["paths"] == [str(source.with_suffix(".xmp"))]
    assert not source.with_suffix(".xmp").exists()
    assert main([*args, "--write"]) == 0
    written = capsys.readouterr()
    assert json.loads(written.out)["written"] is True
    assert "XMP: 1/1" in written.err
    assert source.with_suffix(".xmp").is_file()
    assert source.read_bytes() == before


def test_cli_export_failure_has_no_success_output(
    catalog: ExposureCatalog, capsys: pytest.CaptureFixture[str], exiftool: str
) -> None:
    sidecar = catalog.shot.files[0].path.with_suffix(".xmp")
    sidecar.write_bytes(b"corrupt existing metadata must not be lost")
    assert (
        main(
            [
                "photos",
                "export-xmp",
                str(catalog.session.session_id),
                "--write",
                "--data-dir",
                str(catalog.data),
            ]
        )
        == 1
    )
    failed = capsys.readouterr()
    assert not failed.out
    assert "Export XMP non completato" in failed.err
    assert sidecar.read_bytes() == b"corrupt existing metadata must not be lost"


@pytest.mark.parametrize("command", ["review", "export-xmp"])
def test_missing_catalog_is_not_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    data = tmp_path / "absent"
    args = ["photos", command, str(uuid.uuid4()), "--data-dir", str(data)]
    if command == "review":
        args.append("KEEP")
    assert main(args) == 1
    assert "catalogo non presente" in capsys.readouterr().err
    assert not data.exists()
