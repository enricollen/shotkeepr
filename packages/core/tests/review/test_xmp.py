import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from filelock import FileLock

from shotkeepr.core.adapters.review import xmp
from shotkeepr.core.adapters.review.factory import review_service
from shotkeepr.core.adapters.review.xmp import ExifToolXmpWriter
from shotkeepr.core.domain.catalog import FileKind, ImageFile, Shot
from shotkeepr.core.domain.catalog.review import (
    ReviewError,
    ReviewStatus,
    ShotReview,
    XmpUnavailableError,
)

from ..quality.conftest import ExposureCatalog


def _tags(executable: str, path: Path) -> dict[str, object]:
    result = subprocess.run(  # noqa: S603 -- resolved test executable, no shell
        [executable, "-json", "-n", "--", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)[0]


@pytest.mark.parametrize(
    ("status", "rating", "label"),
    [
        (ReviewStatus.KEEP, 5, "Green"),
        (ReviewStatus.REJECT, -1, "Red"),
        (ReviewStatus.REVIEW, 0, "Yellow"),
    ],
)
def test_real_export_never_modifies_the_original(
    catalog: ExposureCatalog, exiftool: str, status: ReviewStatus, rating: int, label: str
) -> None:
    file = catalog.shot.files[0]
    original, modified = file.path.read_bytes(), file.path.stat().st_mtime_ns
    writer = ExifToolXmpWriter(catalog.data / "locks")
    targets = writer.write(catalog.shot, ShotReview(catalog.shot.shot_id, status))
    assert targets == [file.path.with_suffix(".xmp")]
    tags = _tags(exiftool, targets[0])
    assert tags["Rating"] == rating
    assert tags["Label"] == label
    assert file.path.read_bytes() == original
    assert file.path.stat().st_mtime_ns == modified
    assert sorted(path.name for path in file.path.parent.iterdir()) == ["photo.jpg", "photo.xmp"]


def test_existing_sidecar_is_merged_without_losing_edits(
    catalog: ExposureCatalog, exiftool: str
) -> None:
    sidecar = catalog.shot.files[0].path.with_suffix(".XMP")
    subprocess.run(  # noqa: S603 -- resolved test executable, no shell
        [
            exiftool,
            "-XMP-dc:Description=Existing caption",
            "-XMP-crs:Exposure2012=0.75",
            "-o",
            str(sidecar),
        ],
        capture_output=True,
        check=True,
    )
    sidecar.chmod(0o640)
    before = _tags(exiftool, sidecar)
    service = review_service(catalog.db, catalog.data)
    service.set_status(catalog.shot.shot_id, ReviewStatus.KEEP)
    assert service.export(catalog.shot.shot_id, ReviewStatus.KEEP) == [sidecar]
    after = _tags(exiftool, sidecar)
    assert after["Description"] == before["Description"] == "Existing caption"
    assert after["Exposure2012"] == before["Exposure2012"] == 0.75
    assert after["Rating"] == 5
    assert after["Label"] == "Green"
    assert sidecar.stat().st_mode & 0o777 == 0o640
    service.set_status(catalog.shot.shot_id, ReviewStatus.REJECT)
    service.export(catalog.shot.shot_id, ReviewStatus.REJECT)
    assert _tags(exiftool, sidecar)["Rating"] == -1
    assert _tags(exiftool, sidecar)["Description"] == "Existing caption"
    assert not sidecar.with_suffix(".xmp").exists()


@pytest.mark.parametrize(
    "failure", ["missing", "modified", "symlink", "corrupt-xmp", "readonly", "directory"]
)
def test_unsafe_inputs_leave_sidecars_untouched(
    catalog: ExposureCatalog, exiftool: str, failure: str
) -> None:
    file = catalog.shot.files[0]
    sidecar = file.path.with_suffix(".xmp")
    if failure == "missing":
        file.path.unlink()
    elif failure == "modified":
        file.path.write_bytes(b"x" * file.size)
    elif failure == "symlink":
        sidecar.symlink_to(file.path)
    elif failure == "corrupt-xmp":
        sidecar.write_bytes(b"not an XMP packet")
    elif failure == "readonly":
        file.path.parent.chmod(0o555)
    else:
        sidecar.mkdir()
    previous = sidecar.read_bytes() if sidecar.is_file() else None
    try:
        with pytest.raises(ReviewError):
            ExifToolXmpWriter(catalog.data / "locks").write(
                catalog.shot, ShotReview(catalog.shot.shot_id, ReviewStatus.KEEP)
            )
        if previous is not None:
            assert sidecar.read_bytes() == previous
        assert not list(file.path.parent.glob(".shotkeepr-xmp-*"))
    finally:
        file.path.parent.chmod(0o755)


def test_shared_raw_jpeg_sidecar_is_written_once(catalog: ExposureCatalog, exiftool: str) -> None:
    jpeg = catalog.shot.files[0]
    raw_path = jpeg.path.with_suffix(".NEF")
    raw_path.write_bytes(b"raw content is only read")
    content = raw_path.read_bytes()
    raw = ImageFile(
        raw_path, "NEF", FileKind.RAW, len(content), hashlib.sha256(content).hexdigest()
    )
    catalog.shot.files.append(raw)
    paths = ExifToolXmpWriter(catalog.data / "locks").write(
        catalog.shot, ShotReview(catalog.shot.shot_id, ReviewStatus.KEEP)
    )
    assert len(paths) == 1
    assert _tags(exiftool, paths[0])["Rating"] == 5
    assert raw_path.read_bytes() == content


def test_sidecar_collisions_between_distinct_shots_are_rejected(catalog: ExposureCatalog) -> None:
    file = catalog.shot.files[0]
    other = ImageFile(file.path.with_suffix(".png"), "PNG", FileKind.STANDARD, 1, "a" * 64)
    catalog.shots.add_many([Shot(catalog.session.session_id, "other-shot", files=[other])])
    with pytest.raises(ReviewError, match="scatti distinti"):
        review_service(catalog.db, catalog.data).targets(catalog.shot.shot_id)
    assert not file.path.with_suffix(".xmp").exists()


def test_exiftool_is_resolved_only_for_export(catalog: ExposureCatalog) -> None:
    writer = ExifToolXmpWriter(catalog.data / "locks", executable="missing-shotkeepr-exiftool")
    assert writer.targets(catalog.shot)
    with pytest.raises(XmpUnavailableError):
        writer.write(catalog.shot, ShotReview(catalog.shot.shot_id))


def test_concurrent_export_is_refused_without_writing(
    catalog: ExposureCatalog, exiftool: str
) -> None:
    target = catalog.shot.files[0].path.with_suffix(".xmp")
    locks = catalog.data / "locks"
    locks.mkdir()
    key = hashlib.sha256(str(target).casefold().encode()).hexdigest()
    with (
        FileLock(locks / f"{key}.lock"),
        pytest.raises(ReviewError, match="Export XMP non completato"),
    ):
        ExifToolXmpWriter(locks).write(catalog.shot, ShotReview(catalog.shot.shot_id))
    assert not target.exists()


def test_an_external_sidecar_edit_is_preserved(
    catalog: ExposureCatalog, exiftool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = catalog.shot.files[0].path.with_suffix(".xmp")
    writer = ExifToolXmpWriter(catalog.data / "locks")
    prepare = writer._prepare

    def changed(*args: object, **kwargs: object) -> object:
        result = prepare(*args, **kwargs)
        target.write_bytes(b"external edit must survive")
        return result

    monkeypatch.setattr(writer, "_prepare", changed)
    with pytest.raises(ReviewError, match="altro programma"):
        writer.write(catalog.shot, ShotReview(catalog.shot.shot_id))
    assert target.read_bytes() == b"external edit must survive"


def test_new_sidecar_cannot_overwrite_a_concurrent_creation(
    catalog: ExposureCatalog, exiftool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    link = xmp.os.link
    target = catalog.shot.files[0].path.with_suffix(".xmp")

    def raced(source: Path, destination: Path) -> None:
        target.write_bytes(b"created by another program")
        link(source, destination)

    monkeypatch.setattr(xmp.os, "link", raced)
    with pytest.raises(ReviewError, match="sidecar pubblicati: nessuno"):
        ExifToolXmpWriter(catalog.data / "locks").write(
            catalog.shot, ShotReview(catalog.shot.shot_id)
        )
    assert target.read_bytes() == b"created by another program"
    assert not list(target.parent.glob(".shotkeepr-xmp-*"))


def test_original_changes_during_merge_are_rejected(
    catalog: ExposureCatalog, exiftool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = ExifToolXmpWriter(catalog.data / "locks")
    prepare = writer._prepare
    original = catalog.shot.files[0].path

    def changed(*args: object, **kwargs: object) -> object:
        result = prepare(*args, **kwargs)
        original.write_bytes(b"original changed while export was running")
        return result

    monkeypatch.setattr(writer, "_prepare", changed)
    with pytest.raises(ReviewError, match="Originale modificato durante"):
        writer.write(catalog.shot, ShotReview(catalog.shot.shot_id))
    assert not original.with_suffix(".xmp").exists()


def test_session_export_scans_the_catalog_once(
    catalog: ExposureCatalog, exiftool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = review_service(catalog.db, catalog.data)
    listing = service.shots.list_by_session
    calls: list[object] = []

    def counted(*args: object, **kwargs: object) -> object:
        calls.append(args)
        return listing(*args, **kwargs)

    monkeypatch.setattr(service.shots, "list_by_session", counted)
    exports = service.export_session(catalog.session.session_id, write=True)
    assert len(calls) == 1
    assert len(exports) == 1
    assert exports[0].paths[0].is_file()


def test_session_failure_reports_completed_sidecars_and_keeps_the_previous_review(
    catalog: ExposureCatalog, exiftool: str
) -> None:
    original = catalog.shot.files[0]
    path = original.path.with_name("second.jpg")
    path.write_bytes(b"another original")
    content = path.read_bytes()
    file = ImageFile(
        path, "JPEG", FileKind.STANDARD, len(content), hashlib.sha256(content).hexdigest()
    )
    shot = Shot(catalog.session.session_id, "second", files=[file], capture_time=datetime.now(UTC))
    catalog.shots.add_many([shot])
    path.with_suffix(".xmp").write_bytes(b"invalid sidecar")
    completed: list[Path] = []
    service = review_service(catalog.db, catalog.data)
    with pytest.raises(ReviewError):
        service.export_session(
            catalog.session.session_id,
            write=True,
            progress=lambda index, total, paths: completed.extend(paths),
        )
    assert completed == [original.path.with_suffix(".xmp")]
    assert completed[0].is_file()
    assert path.with_suffix(".xmp").read_bytes() == b"invalid sidecar"
    assert service.get(shot.shot_id).status is ReviewStatus.REVIEW


def test_unknown_xmp_fields_are_preserved(catalog: ExposureCatalog, exiftool: str) -> None:
    sidecar = catalog.shot.files[0].path.with_suffix(".xmp")
    sidecar.write_text(
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:custom="https://example.org/custom/1.0/" '
        'custom:PrivateValue="preserved-value"/>'
        "</rdf:RDF></x:xmpmeta>",
        encoding="utf-8",
    )
    ExifToolXmpWriter(catalog.data / "locks").write(
        catalog.shot, ShotReview(catalog.shot.shot_id, ReviewStatus.KEEP)
    )
    tags = _tags(exiftool, sidecar)
    assert tags["PrivateValue"] == "preserved-value"
    assert tags["Rating"] == 5


def test_ambiguous_sidecar_case_is_refused(catalog: ExposureCatalog, exiftool: str) -> None:
    file = catalog.shot.files[0]
    file.path.with_suffix(".xmp").write_bytes(b"lowercase metadata")
    file.path.with_suffix(".XMP").write_bytes(b"uppercase metadata")
    with pytest.raises(ReviewError, match="ambigue"):
        ExifToolXmpWriter(catalog.data / "locks").write(
            catalog.shot, ShotReview(catalog.shot.shot_id)
        )
    assert file.path.with_suffix(".xmp").read_bytes() == b"lowercase metadata"
    assert file.path.with_suffix(".XMP").read_bytes() == b"uppercase metadata"


def test_readonly_sidecar_is_not_replaced(catalog: ExposureCatalog, exiftool: str) -> None:
    sidecar = catalog.shot.files[0].path.with_suffix(".xmp")
    sidecar.write_bytes(b"protected metadata")
    sidecar.chmod(0o444)
    with pytest.raises(ReviewError, match="sola lettura"):
        ExifToolXmpWriter(catalog.data / "locks").write(
            catalog.shot, ShotReview(catalog.shot.shot_id)
        )
    assert sidecar.read_bytes() == b"protected metadata"


def test_symlinked_source_directory_is_not_followed(
    catalog: ExposureCatalog, exiftool: str
) -> None:
    folder = catalog.session.source_folder
    moved = folder.with_name("moved-originals")
    folder.rename(moved)
    folder.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ReviewError, match="simbolico"):
        ExifToolXmpWriter(catalog.data / "locks").write(
            catalog.shot, ShotReview(catalog.shot.shot_id)
        )
    assert not catalog.shot.files[0].path.with_suffix(".xmp").exists()


def test_a_jpeg_disguised_as_a_sidecar_is_not_overwritten(
    catalog: ExposureCatalog, exiftool: str
) -> None:
    file = catalog.shot.files[0]
    sidecar = file.path.with_suffix(".xmp")
    original = file.path.read_bytes()
    sidecar.write_bytes(original)
    with pytest.raises(ReviewError):
        ExifToolXmpWriter(catalog.data / "locks").write(
            catalog.shot, ShotReview(catalog.shot.shot_id)
        )
    assert sidecar.read_bytes() == original
    assert file.path.read_bytes() == original


def test_parent_traversal_in_catalog_paths_is_rejected(catalog: ExposureCatalog) -> None:
    path = catalog.session.source_folder / ".." / "outside.jpg"
    file = ImageFile(path, "JPEG", FileKind.STANDARD, 10, "a" * 64)
    shot = Shot(catalog.session.session_id, "outside", files=[file])
    catalog.shots.add_many([shot])
    service = review_service(catalog.db, catalog.data)
    with pytest.raises(ReviewError, match="esterno"):
        service.targets(shot.shot_id)
    with pytest.raises(ReviewError, match="esterno"):
        service.export_session(catalog.session.session_id)
    with pytest.raises(ReviewError):
        service.writer.targets(shot)
