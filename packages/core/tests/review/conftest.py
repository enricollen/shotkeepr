import shutil

import pytest

from ..quality.conftest import catalog as catalog  # noqa: PLC0414 -- shared catalog fixture


@pytest.fixture
def exiftool() -> str:
    executable = shutil.which("exiftool")
    if executable is None:
        pytest.skip("ExifTool required for real XMP integration")
    return executable
