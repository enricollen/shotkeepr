import hashlib
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shotkeepr.core.domain.catalog import FileKind, ImageFile, ShotMetadata
from shotkeepr.core.domain.catalog.ingestion import build_shots


def _file(
    path: str, *, kind: FileKind = FileKind.STANDARD, image_format: str = "JPEG"
) -> ImageFile:
    return ImageFile(
        Path(path),
        image_format,
        kind,
        10,
        hashlib.sha256(path.encode()).hexdigest(),
        ShotMetadata(
            camera_model="camera",
            camera_serial="serial",
            capture_time=datetime(2026, 10, 2, tzinfo=UTC),
        ),
    )


def test_matching_raw_jpeg_is_one_shot_regardless_of_extension_case() -> None:
    raw, jpeg = (
        _file("/photos/a.NEF", kind=FileKind.RAW, image_format="NEF"),
        _file("/photos/a.JPG"),
    )
    session_id = uuid.uuid4()
    shots = build_shots(session_id, [raw, jpeg])
    assert len(shots) == 1
    assert shots[0].is_raw_pair
    assert shots[0].session_id == session_id
    assert shots[0].capture_time == raw.metadata.capture_time
    assert shots[0].files == [raw, jpeg]
    assert build_shots(session_id, [jpeg, raw])[0].content_hash == shots[0].content_hash


@pytest.mark.parametrize(
    "mismatch", ["folder", "name", "time", "missing", "camera", "serial", "format", "ambiguous"]
)
def test_unreliable_or_ambiguous_pairs_stay_separate(mismatch: str) -> None:
    raw, jpeg = (
        _file("/photos/a.NEF", kind=FileKind.RAW, image_format="NEF"),
        _file("/photos/a.JPG"),
    )
    files = [raw, jpeg]
    if mismatch == "folder":
        jpeg.path = Path("/other/a.JPG")
    elif mismatch == "name":
        jpeg.path = Path("/photos/b.JPG")
    elif mismatch == "time":
        jpeg.metadata = replace(
            jpeg.metadata, capture_time=jpeg.metadata.capture_time + timedelta(microseconds=1)
        )
    elif mismatch == "missing":
        raw.metadata = replace(raw.metadata, capture_time=None)
        jpeg.metadata = replace(jpeg.metadata, capture_time=None)
    elif mismatch == "camera":
        jpeg.metadata = replace(jpeg.metadata, camera_model="other")
    elif mismatch == "serial":
        jpeg.metadata = replace(jpeg.metadata, camera_serial="other")
    elif mismatch == "format":
        jpeg.format = "PNG"
    else:
        files.append(_file("/photos/a.CR2", kind=FileKind.RAW, image_format="CR2"))
    shots = build_shots(uuid.uuid4(), files)
    assert len(shots) == len(files)
    assert all(not shot.is_raw_pair for shot in shots)


def test_identical_copies_preserve_all_file_paths_without_duplicate_shot_hashes() -> None:
    first, copy = _file("/photos/a.JPG"), _file("/photos/copy.JPG")
    copy.fingerprint = first.fingerprint
    shots = build_shots(uuid.uuid4(), [first, copy])
    assert len(shots) == 1
    assert shots[0].files == [first, copy]


def test_other_formats_with_matching_names_remain_independent() -> None:
    raw, jpeg, png = (
        _file("/photos/a.NEF", kind=FileKind.RAW, image_format="NEF"),
        _file("/photos/a.JPG"),
        _file("/photos/a.png", image_format="PNG"),
    )
    shots = build_shots(uuid.uuid4(), [raw, jpeg, png])
    assert len(shots) == 2
    assert len(shots[0].files) == 2
    assert shots[1].files == [png]
