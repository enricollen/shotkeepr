"""Esposizione RGB 8 bit su miniature: nessuna lettura o scrittura degli originali."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from shotkeepr.core.adapters.quality.preview import (
    MAX_PREVIEW_BYTES as MAX_PREVIEW_BYTES,  # noqa: PLC0414 -- public compatibility constant
)
from shotkeepr.core.adapters.quality.preview import preview_pixels, read_preview
from shotkeepr.core.domain.quality.exposure import ExposureError, ExposureMetrics

SHADOW_LIMIT = 5
HIGHLIGHT_LIMIT = 250


class PillowExposureAnalyzer:
    version = "preview-rgb-exposure-v1"

    def read(self, preview: Path) -> bytes:
        return read_preview(preview, ExposureError)

    def measure(self, content: bytes) -> ExposureMetrics:
        pixels = preview_pixels(content, ExposureError)
        height, width, _channels = pixels.shape
        # Un canale saturo perde colore anche quando la luminanza complessiva e' bassa.
        highlights = np.any(pixels >= HIGHLIGHT_LIMIT, axis=2)
        shadows = np.all(pixels <= SHADOW_LIMIT, axis=2)
        luma = pixels @ np.array([0.2126, 0.7152, 0.0722]) / 255
        return ExposureMetrics(
            width=width,
            height=height,
            mean_luma=float(np.mean(luma)),
            highlights_fraction=float(np.mean(highlights)),
            shadows_fraction=float(np.mean(shadows)),
        )
