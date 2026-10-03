"""Indicatori di esposizione dell'anteprima, non della gamma dinamica RAW."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


class ExposureError(RuntimeError):
    """La misura non puo' essere completata o salvata."""


class ExposureShotNotFoundError(ExposureError):
    """Lo scatto non esiste nel catalogo."""


@dataclass(frozen=True, slots=True)
class ExposureMetrics:
    width: int
    height: int
    mean_luma: float
    highlights_fraction: float
    shadows_fraction: float

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError("dimensioni dell'anteprima non valide")
        values = (self.mean_luma, self.highlights_fraction, self.shadows_fraction)
        if any(not 0 <= value <= 1 for value in values):
            raise ValueError("le misure di esposizione devono essere comprese tra 0 e 1")
        if self.highlights_fraction + self.shadows_fraction > 1:
            raise ValueError("alte luci e ombre non possono sovrapporsi")

    @property
    def score(self) -> float:
        return 100 * max(0.0, 1 - self.highlights_fraction - self.shadows_fraction)


@dataclass(frozen=True, slots=True)
class ExposureMeasurement:
    shot_id: uuid.UUID
    source_fingerprint: str
    preview_sha256: str
    analyzer_version: str
    measured_at: datetime
    metrics: ExposureMetrics

    def __post_init__(self) -> None:
        for digest in (self.source_fingerprint, self.preview_sha256):
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("impronta di esposizione non valida")
        if not self.analyzer_version.strip():
            raise ValueError("versione dell'analizzatore obbligatoria")
        if self.measured_at.tzinfo is None:
            raise ValueError("data della misura senza fuso orario")
