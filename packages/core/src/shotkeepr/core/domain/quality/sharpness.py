"""Global preview detail indicators, not subject focus or a photographic score."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime


class SharpnessError(RuntimeError):
    """The measurement cannot be completed safely."""


class SharpnessShotNotFoundError(SharpnessError):
    """The shot is absent from the catalog."""


@dataclass(frozen=True, slots=True)
class SharpnessMetrics:
    width: int
    height: int
    laplacian_variance: float
    gradient_energy: float

    def __post_init__(self) -> None:
        if min(self.width, self.height) < 3:
            raise ValueError("dimensioni dell'anteprima insufficienti per la nitidezza")
        if not math.isfinite(self.laplacian_variance) or not 0 <= self.laplacian_variance <= 16:
            raise ValueError("varianza del Laplaciano non valida")
        if not math.isfinite(self.gradient_energy) or not 0 <= self.gradient_energy <= 1:
            raise ValueError("energia dei gradienti non valida")


@dataclass(frozen=True, slots=True)
class SharpnessMeasurement:
    shot_id: uuid.UUID
    source_fingerprint: str
    preview_sha256: str
    analyzer_version: str
    measured_at: datetime
    metrics: SharpnessMetrics

    def __post_init__(self) -> None:
        for digest in (self.source_fingerprint, self.preview_sha256):
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("impronta di nitidezza non valida")
        if not self.analyzer_version.strip():
            raise ValueError("versione dell'analizzatore obbligatoria")
        if self.measured_at.utcoffset() is None:
            raise ValueError("data della misura senza fuso orario")
