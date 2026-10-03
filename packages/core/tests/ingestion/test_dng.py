"""Decodifica LibRaw reale su un piccolo DNG sintetico, senza campioni esterni."""

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, TiffImagePlugin

from shotkeepr.core.adapters.ingestion.previews import PillowRawPreviewStore
from shotkeepr.core.adapters.ingestion.source import ExifToolPhotoSource
from shotkeepr.core.domain.catalog import FileKind


def test_real_synthetic_dng_decode_without_embedded_thumbnail(
    exiftool: str, tmp_path: Path
) -> None:
    path = tmp_path / "synthetic.dng"
    tags = TiffImagePlugin.ImageFileDirectory_v2()
    tags[262] = 32803  # Color Filter Array (Bayer).
    tags[271] = "ShotKeepr"
    tags[272] = "Synthetic Camera"
    tags[33421] = (2, 2)
    tags[33422] = bytes([0, 1, 1, 2])
    tags[50706] = bytes([1, 4, 0, 0])
    tags[50707] = bytes([1, 1, 0, 0])
    tags[50708] = "ShotKeepr Synthetic Camera"
    tags[50714] = 0
    tags[50717] = 65535
    tags[50721] = tuple(TiffImagePlugin.IFDRational(value) for value in (1, 0, 0, 0, 1, 0, 0, 0, 1))
    tags[50728] = (TiffImagePlugin.IFDRational(1),) * 3
    tags[50778] = 21
    pixels = np.arange(128 * 96, dtype=np.uint16).reshape(96, 128) * 4 + 1024
    with Image.fromarray(pixels) as image:
        image.save(path, format="TIFF", tiffinfo=tags)
    original = path.read_bytes()
    file = ExifToolPhotoSource(executable=exiftool).inspect(path)
    assert file.format == "DNG"
    assert file.kind == FileKind.RAW
    thumbnail = PillowRawPreviewStore(tmp_path / "cache").create(file)
    with Image.open(thumbnail) as preview:
        assert preview.format == "JPEG"
        assert 0 < preview.width <= 512
        assert 0 < preview.height <= 512
    assert file.fingerprint == hashlib.sha256(original).hexdigest()
    assert path.read_bytes() == original
