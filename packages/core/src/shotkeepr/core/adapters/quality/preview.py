"""Bounded JPEG input shared by deterministic preview measurements."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

from shotkeepr.core.adapters.ingestion.previews import PREVIEW_SIZE

MAX_PREVIEW_BYTES = 2 * 1024 * 1024


def read_preview(preview: Path, error: type[RuntimeError]) -> bytes:
    try:
        with preview.open("rb") as stream:
            content = stream.read(MAX_PREVIEW_BYTES + 1)
    except OSError as exc:
        raise error("anteprima non accessibile: ripristinare la cache") from exc
    if not content or len(content) > MAX_PREVIEW_BYTES:
        raise error("dimensione del file anteprima non valida")
    return content


def preview_pixels(
    content: bytes, error: type[RuntimeError], *, min_side: int = 1
) -> NDArray[np.float64]:
    if not content or len(content) > MAX_PREVIEW_BYTES:
        raise error("dimensione del file anteprima non valida")
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format != "JPEG" or min(image.size) < 1 or max(image.size) > PREVIEW_SIZE:
                raise error("la misura richiede una miniatura JPEG fino a 512 pixel")
            if min(image.size) < min_side:
                raise error(f"anteprima troppo piccola: servono almeno {min_side} pixel per lato")
            with image.convert("RGB") as rgb:
                return np.asarray(rgb, dtype=np.float64)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise error("anteprima corrotta: ripristinare la cache") from exc
