"""Registro dei modelli: selezione esplicita della versione e accesso tramite porta."""

from pathlib import Path

from shotkeepr.core.application.ports import DownloadProgress, ModelStore
from shotkeepr.core.domain.models.model import ModelManifest


class ModelRegistry:
    def __init__(self, manifest: ModelManifest, store: ModelStore) -> None:
        self.manifest = manifest
        self._store = store

    def fetch(
        self,
        model_id: str,
        version: str | None = None,
        *,
        progress: DownloadProgress | None = None,
    ) -> Path:
        return self._store.fetch(self.manifest.select(model_id, version), progress=progress)

    def verify(self, model_id: str, version: str | None = None) -> Path:
        return self._store.verify(self.manifest.select(model_id, version))
