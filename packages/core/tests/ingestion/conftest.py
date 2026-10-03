import hashlib
import shutil
from pathlib import Path

import pytest
from PIL import Image, TiffImagePlugin

from shotkeepr.core.domain.catalog import FileKind, ImageFile


@pytest.fixture
def exiftool() -> str:
    executable = shutil.which("exiftool")
    if executable is None:
        pytest.skip("ExifTool richiesto per i test di integrazione fotografica")
    return executable


@pytest.fixture
def photograph(tmp_path: Path) -> ImageFile:
    folder = tmp_path / "photos"
    folder.mkdir()
    path = folder / "photo.jpg"
    exif = Image.Exif()
    exif[272] = "Test Camera"
    exif[274] = 6
    exif[34665] = {
        36867: "2026:10:02 10:00:00",
        36881: "+02:00",
        37521: "125",
        42033: "CAM-123",
        42036: "Test Lens",
        37386: TiffImagePlugin.IFDRational(50),
        33434: TiffImagePlugin.IFDRational(1, 100),
        33437: TiffImagePlugin.IFDRational(4),
        34855: 400,
    }
    with Image.new("RGB", (1000, 600), "navy") as image:
        image.save(path, exif=exif)
    content = path.read_bytes()
    return ImageFile(
        path, "JPEG", FileKind.STANDARD, len(content), hashlib.sha256(content).hexdigest()
    )
