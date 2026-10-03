import json
import uuid
from pathlib import Path

import pytest
from PIL import Image

from shotkeepr.core.__main__ import main
from shotkeepr.core.adapters.ingestion import source
from shotkeepr.core.domain.catalog import ImageFile


def test_cli_import_list_show_and_preview_cache_are_persistent(
    exiftool: str,
    photograph: ImageFile,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = photograph.path.parent
    (folder / "notes.txt").write_text("not an image", encoding="utf-8")
    (folder / "copy.jpg").write_bytes(photograph.path.read_bytes())
    data = tmp_path / "data"
    assert main(["photos", "import", str(folder), "--data-dir", str(data)]) == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert "file:" in captured.err
    assert summary["status"] == "IMPORTED"
    assert summary["analysis_performed"] is False
    assert summary["files"] == 2
    assert summary["shots"] == 1
    assert len(summary["excluded"]) == 1
    assert summary["raw_pairs"] == 0
    session_id = summary["session_id"]
    assert main(["photos", "list", "--data-dir", str(data)]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["sessions"][0]["session_id"] == session_id
    assert main(["photos", "show", session_id, "--data-dir", str(data)]) == 0
    detail = json.loads(capsys.readouterr().out)
    files = detail["shots"][0]["files"]
    assert {file["path"] for file in files} == {str(photograph.path), str(folder / "copy.jpg")}
    assert files[0]["metadata"]["camera_model"] == "Test Camera"
    assert files[0]["metadata"]["capture_time"] == "2026-10-02T08:00:00.125000+00:00"
    previews = {Path(file["preview_path"]) for file in files}
    assert len(previews) == 1
    before = {path: path.stat().st_mtime_ns for path in previews}
    assert main(["photos", "import", str(folder), "--data-dir", str(data)]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["session_id"] != session_id
    assert again["shots"] == 1
    assert {path: path.stat().st_mtime_ns for path in previews} == before


@pytest.mark.parametrize("recursive", [True, False])
def test_cli_subfolder_option(
    exiftool: str, tmp_path: Path, capsys: pytest.CaptureFixture[str], recursive: bool
) -> None:
    folder = tmp_path / "photos"
    nested = folder / "sub"
    nested.mkdir(parents=True)
    with Image.new("RGB", (64, 32), "green") as image:
        image.save(nested / "picture.png")
    arguments = ["photos", "import", str(folder), "--data-dir", str(tmp_path / "data")]
    if not recursive:
        arguments.append("--no-subfolders")
    assert main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["include_subfolders"] is recursive
    assert result["files"] == (1 if recursive else 0)


def test_cli_rejects_data_inside_originals_without_writing(
    exiftool: str,
    photograph: ImageFile,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = photograph.path.parent / "cache-and-database"
    assert main(["photos", "import", str(photograph.path.parent), "--data-dir", str(data)]) == 1
    assert "esterni" in capsys.readouterr().err
    assert not data.exists()


def test_cli_missing_exiftool_does_not_create_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(source.shutil, "which", lambda executable: None)
    data = tmp_path / "data"
    assert main(["photos", "import", str(tmp_path), "--data-dir", str(data)]) == 1
    assert "ExifTool" in capsys.readouterr().err
    assert not data.exists()


def test_cli_reading_missing_catalog_does_not_create_empty_success(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = tmp_path / "absent"
    assert main(["photos", "list", "--data-dir", str(data)]) == 1
    assert "catalogo non presente" in capsys.readouterr().err
    assert not data.exists()


def test_cli_show_unknown_session_is_an_error(
    exiftool: str,
    photograph: ImageFile,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = tmp_path / "data"
    assert main(["photos", "import", str(photograph.path.parent), "--data-dir", str(data)]) == 0
    capsys.readouterr()
    assert main(["photos", "show", str(uuid.uuid4()), "--data-dir", str(data)]) == 1
    assert "sessione non presente" in capsys.readouterr().err


@pytest.mark.parametrize("arguments", [["photos"], ["photos", "show", "not-a-uuid"]])
def test_cli_requires_valid_subcommand_and_session_identifier(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(arguments)
    assert exc.value.code == 2
