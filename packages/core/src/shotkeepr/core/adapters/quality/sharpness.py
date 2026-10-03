"""NumPy Laplacian and gradients on bounded cached JPEGs, without original access."""

from pathlib import Path

import numpy as np

from shotkeepr.core.adapters.quality.preview import preview_pixels, read_preview
from shotkeepr.core.domain.quality.sharpness import SharpnessError, SharpnessMetrics


class PillowSharpnessAnalyzer:
    version = "preview-luma-laplacian-v1"

    def read(self, preview: Path) -> bytes:
        return read_preview(preview, SharpnessError)

    def measure(self, content: bytes) -> SharpnessMetrics:
        pixels = preview_pixels(content, SharpnessError, min_side=3)
        height, width, _channels = pixels.shape
        luma = pixels @ np.array([0.2126, 0.7152, 0.0722]) / 255
        laplacian = (
            luma[:-2, 1:-1]
            + luma[2:, 1:-1]
            + luma[1:-1, :-2]
            + luma[1:-1, 2:]
            - 4 * luma[1:-1, 1:-1]
        )
        gradient_energy = (
            np.mean(np.square(np.diff(luma, axis=0))) + np.mean(np.square(np.diff(luma, axis=1)))
        ) / 2
        return SharpnessMetrics(width, height, float(np.var(laplacian)), float(gradient_energy))
