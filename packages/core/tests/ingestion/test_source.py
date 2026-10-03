import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from shotkeepr.core.adapters.ingestion import source
from shotkeepr.core.adapters.ingestion.source import (
    RAW_FORMATS,
    ExifToolPhotoSource,
    metadata_from_tags,
)
from shotkeepr.core.domain.catalog import ExcludedFile, ExclusionReason, FileKind, ImageFile
from shotkeepr.core.domain.catalog.ingestion import CatalogImportError, FileInspectionError


def test_real_exiftool_reads_content_and_precise_metadata(
    exiftool: str, photograph: ImageFile
) -> None:
    original = photograph.path.read_bytes()
    photograph.path = photograph.path.rename(photograph.path.with_suffix(".txt"))
    file = ExifToolPhotoSource(executable=exiftool).inspect(photograph.path)
    assert file.format == "JPEG"
    assert file.kind == FileKind.STANDARD
    assert file.fingerprint == hashlib.sha256(original).hexdigest()
    assert file.metadata.camera_model == "Test Camera"
    assert file.metadata.camera_serial == "CAM-123"
    assert file.metadata.lens == "Test Lens"
    assert file.metadata.focal_mm == 50
    assert file.metadata.exposure_s == 0.01
    assert file.metadata.aperture == 4
    assert file.metadata.iso == 400
    assert file.metadata.capture_time == datetime(2026, 10, 2, 8, 0, 0, 125000, tzinfo=UTC)
    assert photograph.path.read_bytes() == original


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "TIFF", "WEBP", "HEIF"])
def test_standard_formats_are_detected_by_content(
    exiftool: str,
    tmp_path: Path,
    image_format: str,
) -> None:
    # Le estensioni non guidano il riconoscimento, incluso HEIC via pillow-heif.
    from shotkeepr.core.adapters.ingestion import previews  # noqa: PLC0415, F401

    path = tmp_path / "renamed.bin"
    with Image.new("RGB", (64, 40), "red") as image:
        image.save(path, format=image_format)
    file = ExifToolPhotoSource(executable=exiftool).inspect(path)
    assert file.format == ("HEIC" if image_format == "HEIF" else image_format)
    assert file.kind == FileKind.STANDARD
    assert file.metadata.capture_time is None


@pytest.mark.parametrize("image_format", sorted(RAW_FORMATS))
def test_raw_classification_uses_exiftool_content_not_suffix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    image_format: str,
) -> None:
    monkeypatch.setattr(source.shutil, "which", lambda executable: "exiftool")
    monkeypatch.setattr(
        source.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [],
            0,
            json.dumps([{"FileType": image_format}]),
            "",
        ),
    )
    path = tmp_path / "renamed.bin"
    path.write_bytes(b"synthetic content for classification")
    file = ExifToolPhotoSource().inspect(path)
    assert file.kind == FileKind.RAW
    assert file.format == image_format


def test_scanner_recursion_and_symlinks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(source.shutil, "which", lambda executable: "exiftool")
    (tmp_path / "a.jpg").write_bytes(b"a")
    child = tmp_path / "sub"
    child.mkdir()
    (child / "b.jpg").write_bytes(b"b")
    scanner = ExifToolPhotoSource()
    assert list(scanner.scan(tmp_path, recursive=False)) == [tmp_path / "a.jpg"]
    assert list(scanner.scan(tmp_path, recursive=True)) == [tmp_path / "a.jpg", child / "b.jpg"]
    try:
        (child / "cycle").symlink_to(tmp_path, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink non disponibile: {exc}")
    scanned = list(scanner.scan(tmp_path, recursive=True))
    assert len(scanned) == 3
    assert isinstance(scanned[-1], ExcludedFile)
    assert scanned[-1].reason == ExclusionReason.UNREADABLE


def test_missing_exiftool_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(source.shutil, "which", lambda executable: None)
    with pytest.raises(CatalogImportError, match="ExifTool non disponibile"):
        ExifToolPhotoSource()


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"DateTimeOriginal": "invalid", "ISO": "not-a-number"},
        {"DateTimeOriginal": "2026:00:00 00:00:00", "ISO": True},
        {"FocalLength": float("nan"), "FNumber": -1, "ExposureTime": [], "ISO": float("inf")},
    ],
)
def test_missing_or_invalid_metadata_is_recorded_as_absent(data: dict[str, object]) -> None:
    metadata = metadata_from_tags(data)
    assert metadata.capture_time is None
    assert metadata.iso is None
    assert metadata.focal_mm is None
    assert metadata.aperture is None
    assert metadata.exposure_s is None


def test_camera_wall_time_without_offset_uses_documented_utc_convention() -> None:
    assert metadata_from_tags(
        {"DateTimeOriginal": "2026:10:02 10:00:00", "SubSecTimeOriginal": "12"}
    ).capture_time == datetime(2026, 10, 2, 10, 0, 0, 120000, tzinfo=UTC)


@pytest.mark.parametrize(
    ("stdout", "exit_code", "error"),
    [
        ("not-json", 0, CatalogImportError),
        ("{}", 0, CatalogImportError),
        ("[]", 0, CatalogImportError),
        ('[{"FileType":"JPEG"}]', 1, FileInspectionError),
        ('[{"Error":"File format error"}]', 1, FileInspectionError),
        ('[{"FileType":"GIF"}]', 0, FileInspectionError),
    ],
)
def test_exiftool_failures_are_not_silent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stdout: str,
    exit_code: int,
    error: type[Exception],
) -> None:
    monkeypatch.setattr(source.shutil, "which", lambda executable: "exiftool")
    monkeypatch.setattr(
        source.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], exit_code, stdout, ""),
    )
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"broken")
    with pytest.raises(error):
        ExifToolPhotoSource().inspect(path)


def test_exiftool_timeout_is_per_file_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(source.shutil, "which", lambda executable: "exiftool")

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired("exiftool", 30)

    monkeypatch.setattr(source.subprocess, "run", timed_out)
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"photo")
    with pytest.raises(FileInspectionError) as error:
        ExifToolPhotoSource().inspect(path)
    assert error.value.reason == ExclusionReason.UNREADABLE
