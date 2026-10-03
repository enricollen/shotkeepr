import io
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rawpy
from PIL import Image

from shotkeepr.core.adapters.ingestion import previews
from shotkeepr.core.adapters.ingestion.previews import PillowRawPreviewStore
from shotkeepr.core.domain.catalog import ExclusionReason, FileKind, ImageFile
from shotkeepr.core.domain.catalog.ingestion import CatalogImportError, FileInspectionError


def test_thumbnail_orientation_size_cache_and_original_integrity(
    photograph: ImageFile, tmp_path: Path
) -> None:
    store = PillowRawPreviewStore(tmp_path / "cache")
    original, modified = photograph.path.read_bytes(), photograph.path.stat().st_mtime_ns
    store.validate_destination(photograph.path.parent)
    thumbnail = store.create(photograph)
    with Image.open(thumbnail) as image:
        assert image.format == "JPEG"
        assert image.width < image.height <= 512
    timestamp = thumbnail.stat().st_mtime_ns
    assert store.create(photograph) == thumbnail
    assert thumbnail.stat().st_mtime_ns == timestamp
    assert photograph.path.read_bytes() == original
    assert photograph.path.stat().st_mtime_ns == modified
    assert list(store.root.rglob("*.part")) == []


def test_cache_cannot_be_inside_the_source(photograph: ImageFile) -> None:
    with pytest.raises(CatalogImportError, match="esterna"):
        PillowRawPreviewStore(photograph.path.parent / "cache").validate_destination(
            photograph.path.parent
        )


def test_stale_fingerprint_is_rejected_without_publishing(
    photograph: ImageFile, tmp_path: Path
) -> None:
    store = PillowRawPreviewStore(tmp_path / "cache")
    photograph.fingerprint = "0" * 64
    with pytest.raises(FileInspectionError) as exc:
        store.create(photograph)
    assert exc.value.reason == ExclusionReason.UNREADABLE
    assert not store.root.exists()


def test_bad_cached_preview_fails_explicitly(photograph: ImageFile, tmp_path: Path) -> None:
    store = PillowRawPreviewStore(tmp_path / "cache")
    path = store.create(photograph)
    path.write_bytes(b"broken")
    with pytest.raises(CatalogImportError, match="cache corrotta"):
        store.create(photograph)


def test_corrupted_standard_file_is_excluded(photograph: ImageFile, tmp_path: Path) -> None:
    photograph.path.write_bytes(b"broken")
    with pytest.raises(FileInspectionError) as exc:
        PillowRawPreviewStore(tmp_path / "cache").create(photograph)
    assert exc.value.reason == ExclusionReason.CORRUPTED


def test_cache_failure_cleans_atomic_temporary_file(
    photograph: ImageFile,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(self: Image.Image, *args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Image.Image, "save", fail)
    store = PillowRawPreviewStore(tmp_path / "cache")
    with pytest.raises(OSError, match="disk full"):
        store.create(photograph)
    assert not store.path_for(photograph).exists()
    assert not list(store.root.rglob("*.part"))


@pytest.mark.parametrize("embedded", [True, False])
def test_raw_preview_uses_embedded_jpeg_or_half_size_decode(
    photograph: ImageFile,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    embedded: bool,
) -> None:
    stream = io.BytesIO()
    with Image.new("RGB", (80, 40), "red") as image:
        image.save(stream, format="JPEG")
    calls: list[str] = []

    class FakeRaw:
        sizes = SimpleNamespace(flip=6)

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            calls.append("closed")

        def extract_thumb(self):
            if not embedded:
                raise rawpy.LibRawNoThumbnailError("missing")
            return SimpleNamespace(format=rawpy.ThumbFormat.JPEG, data=stream.getvalue())

        def postprocess(self, *, half_size: bool, use_camera_wb: bool, output_bps: int):
            assert half_size and use_camera_wb and output_bps == 8
            calls.append("postprocess")
            return np.zeros((80, 40, 3), dtype=np.uint8)

    monkeypatch.setattr(previews.rawpy, "imread", lambda path: FakeRaw())
    raw = replace(photograph, kind=FileKind.RAW, format="NEF")
    path = PillowRawPreviewStore(tmp_path / "cache").create(raw)
    with Image.open(path) as image:
        assert image.size == (40, 80)
    assert calls == (["closed"] if embedded else ["postprocess", "closed"])


def test_corrupted_raw_is_excluded(photograph: ImageFile, tmp_path: Path) -> None:
    raw = replace(photograph, kind=FileKind.RAW, format="NEF")
    with pytest.raises(FileInspectionError) as exc:
        PillowRawPreviewStore(tmp_path / "cache").create(raw)
    assert exc.value.reason == ExclusionReason.CORRUPTED


def test_invalid_fingerprint_cannot_escape_cache(photograph: ImageFile, tmp_path: Path) -> None:
    photograph.fingerprint = "../../elsewhere"
    with pytest.raises(CatalogImportError, match="impronta"):
        PillowRawPreviewStore(tmp_path / "cache").path_for(photograph)


def test_truncated_jpeg_cache_is_not_mistaken_for_a_valid_thumbnail(
    photograph: ImageFile,
    tmp_path: Path,
) -> None:
    store = PillowRawPreviewStore(tmp_path / "cache")
    path = store.create(photograph)
    content = path.read_bytes()
    path.write_bytes(content[: len(content) // 2])
    with pytest.raises(CatalogImportError, match="cache corrotta"):
        store.create(photograph)
