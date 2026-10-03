"""Explicit preview sharpness, cached only for unchanged content and method."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from shotkeepr.core.application.ports import (
    PreviewStore,
    SharpnessAnalyzer,
    SharpnessRepository,
    ShotRepository,
)
from shotkeepr.core.domain.catalog.ingestion import CatalogImportError
from shotkeepr.core.domain.quality.sharpness import (
    SharpnessError,
    SharpnessMeasurement,
    SharpnessShotNotFoundError,
)


class SharpnessService:
    def __init__(
        self,
        shots: ShotRepository,
        previews: PreviewStore,
        results: SharpnessRepository,
        analyzer: SharpnessAnalyzer,
    ) -> None:
        self.shots, self.results = shots, results
        self._previews, self._analyzer = previews, analyzer

    def measure(self, shot_id: uuid.UUID) -> SharpnessMeasurement:
        shot = self.shots.get(shot_id)
        if shot is None:
            raise SharpnessShotNotFoundError("scatto non presente nel catalogo")
        file = shot.preview_file
        if file is None:
            raise SharpnessError("lo scatto non contiene file immagine")
        try:
            preview = self._previews.path_for(file)
        except CatalogImportError as exc:
            raise SharpnessError(str(exc)) from exc
        content = self._analyzer.read(preview)
        digest = hashlib.sha256(content).hexdigest()
        previous = self.results.get(shot_id)
        if (
            previous is not None
            and previous.source_fingerprint == file.fingerprint
            and previous.preview_sha256 == digest
            and previous.analyzer_version == self._analyzer.version
        ):
            return previous
        result = SharpnessMeasurement(
            shot_id,
            file.fingerprint,
            digest,
            self._analyzer.version,
            datetime.now(UTC),
            self._analyzer.measure(content),
        )
        self.results.save(result)
        return result
