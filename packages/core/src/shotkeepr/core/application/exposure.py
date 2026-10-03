"""Misura esplicita per scatto, riusabile solo con anteprima e algoritmo invariati."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from shotkeepr.core.application.ports import (
    ExposureAnalyzer,
    ExposureRepository,
    PreviewStore,
    ShotRepository,
)
from shotkeepr.core.domain.catalog.ingestion import CatalogImportError
from shotkeepr.core.domain.quality.exposure import (
    ExposureError,
    ExposureMeasurement,
    ExposureShotNotFoundError,
)


class ExposureService:
    def __init__(
        self,
        shots: ShotRepository,
        previews: PreviewStore,
        results: ExposureRepository,
        analyzer: ExposureAnalyzer,
    ) -> None:
        self.shots = shots
        self.results = results
        self._previews = previews
        self._analyzer = analyzer

    def measure(self, shot_id: uuid.UUID) -> ExposureMeasurement:
        shot = self.shots.get(shot_id)
        if shot is None:
            raise ExposureShotNotFoundError("scatto non presente nel catalogo")
        file = shot.preview_file
        if file is None:
            raise ExposureError("lo scatto non contiene file immagine")
        try:
            path = self._previews.path_for(file)
        except CatalogImportError as exc:
            raise ExposureError(str(exc)) from exc
        content = self._analyzer.read(path)
        digest = hashlib.sha256(content).hexdigest()
        previous = self.results.get(shot_id)
        if (
            previous is not None
            and previous.source_fingerprint == file.fingerprint
            and previous.preview_sha256 == digest
            and previous.analyzer_version == self._analyzer.version
        ):
            return previous
        measurement = ExposureMeasurement(
            shot_id=shot_id,
            source_fingerprint=file.fingerprint,
            preview_sha256=digest,
            analyzer_version=self._analyzer.version,
            measured_at=datetime.now(UTC),
            metrics=self._analyzer.measure(content),
        )
        self.results.save(measurement)
        return measurement
