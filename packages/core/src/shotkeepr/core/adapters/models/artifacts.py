"""Download in streaming e cache atomica dei modelli, con lock tra processi."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
from filelock import FileLock, Timeout

from shotkeepr.core.application.ports import DownloadProgress
from shotkeepr.core.domain.models.model import (
    InvalidModelManifestError,
    ModelArtifact,
    ModelDownloadError,
    ModelError,
    ModelIntegrityError,
    ModelManifest,
    validate_model_url,
)

CHUNK_SIZE = 64 * 1024
MAX_REDIRECTS = 5
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


def _unique_fields(fields: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in fields:
        if key in result:
            raise InvalidModelManifestError(f"campo duplicato nel manifest: {key}")
        result[key] = value
    return result


def load_manifest(path: Path) -> ModelManifest:
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_fields)
    if not isinstance(data, dict) or set(data) != {"schema_version", "models"}:
        raise InvalidModelManifestError("struttura del manifest non valida")
    if not isinstance(data["models"], list):
        raise InvalidModelManifestError("models deve essere un elenco")
    models: list[ModelArtifact] = []
    for record in data["models"]:
        if not isinstance(record, dict):
            raise InvalidModelManifestError("ogni modello deve essere un oggetto")
        models.append(ModelArtifact.from_dict(record))
    return ModelManifest(tuple(models), schema_version=data["schema_version"])


class VerifiedModelStore:
    def __init__(self, root: Path, *, client: httpx.Client | None = None) -> None:
        self._root = root.resolve()
        self._client = client

    def _path(self, artifact: ModelArtifact) -> Path:
        path = self._root / artifact.model_id / artifact.version / f"{artifact.sha256}.onnx"
        if not path.resolve().is_relative_to(self._root) or path.is_symlink():
            raise ModelError("la cache dei modelli contiene un percorso non sicuro")
        return path

    @staticmethod
    def _verify(path: Path, artifact: ModelArtifact) -> None:
        if not path.is_file():
            raise ModelError(
                f"pesi non presenti nella cache: {artifact.model_id} {artifact.version}"
            )
        if path.stat().st_size != artifact.size_bytes:
            raise ModelIntegrityError(f"dimensione non valida per {artifact.model_id}")
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != artifact.sha256:
            raise ModelIntegrityError(f"SHA-256 non valido per {artifact.model_id}")

    @staticmethod
    @contextmanager
    def _locked(path: Path) -> Iterator[None]:
        lock = path.parent / ".download.lock"
        if lock.is_symlink():
            raise ModelError("il lock della cache non puo' essere un collegamento simbolico")
        try:
            with FileLock(str(lock), timeout=60):
                yield
        except Timeout as exc:
            raise ModelError("cache dei modelli occupata: riprovare piu' tardi") from exc

    def verify(self, artifact: ModelArtifact) -> Path:
        path = self._path(artifact)
        if not path.parent.is_dir():
            raise ModelError(
                f"pesi non presenti nella cache: {artifact.model_id} {artifact.version}"
            )
        with self._locked(path):
            self._verify(path, artifact)
        return path

    def fetch(self, artifact: ModelArtifact, *, progress: DownloadProgress | None = None) -> Path:
        path = self._path(artifact)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked(path):
            if path.exists():
                self._verify(path, artifact)
            else:
                self._download(path, artifact, progress)
            self._write_record(path, artifact)
            if progress is not None:
                progress(artifact.size_bytes, artifact.size_bytes)
        return path

    @staticmethod
    def _write_record(path: Path, artifact: ModelArtifact) -> None:
        record = {**artifact.to_dict(), "verified_at": datetime.now(UTC).isoformat()}
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            suffix=".json.part",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        try:
            temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
            temporary.replace(path.with_suffix(".json"))
        finally:
            temporary.unlink(missing_ok=True)

    def _download(
        self,
        path: Path,
        artifact: ModelArtifact,
        progress: DownloadProgress | None,
    ) -> None:
        client_context = (
            nullcontext(self._client)
            if self._client is not None
            else httpx.Client(
                timeout=httpx.Timeout(30, connect=10),
                follow_redirects=False,
                trust_env=False,
            )
        )
        with client_context as client:
            try:
                self._stream(client, path, artifact, progress)
            except httpx.HTTPError as exc:
                raise ModelDownloadError(f"download HTTPS fallito per {artifact.model_id}") from exc

    def _stream(
        self,
        client: httpx.Client,
        path: Path,
        artifact: ModelArtifact,
        progress: DownloadProgress | None,
    ) -> None:
        url = artifact.url
        for _ in range(MAX_REDIRECTS + 1):
            validate_model_url(url)
            with client.stream(
                "GET", url, headers={"Accept-Encoding": "identity"}, follow_redirects=False
            ) as response:
                if response.status_code in _REDIRECTS:
                    location = response.headers.get("location")
                    if not location:
                        raise ModelDownloadError("redirect del modello senza destinazione")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                if response.status_code != 200:
                    raise ModelDownloadError(
                        "il download del modello richiede una risposta HTTP 200"
                    )
                if response.headers.get("content-encoding", "identity") not in {"", "identity"}:
                    raise ModelDownloadError("compressione HTTP del modello non supportata")
                self._save_response(response, path, artifact, progress)
                return
        raise ModelDownloadError("troppi redirect nel download del modello")

    def _save_response(
        self,
        response: httpx.Response,
        path: Path,
        artifact: ModelArtifact,
        progress: DownloadProgress | None,
    ) -> None:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, suffix=".onnx.part", delete=False
        ) as handle:
            temporary = Path(handle.name)
        try:
            size = 0
            digest = hashlib.sha256()
            if progress is not None:
                progress(0, artifact.size_bytes)
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
                    size += len(chunk)
                    if size > artifact.size_bytes:
                        raise ModelIntegrityError(
                            f"modello piu' grande del previsto: {artifact.model_id}"
                        )
                    digest.update(chunk)
                    output.write(chunk)
                    if progress is not None:
                        progress(size, artifact.size_bytes)
            if size != artifact.size_bytes or digest.hexdigest() != artifact.sha256:
                raise ModelIntegrityError(
                    f"dimensione o SHA-256 non validi per {artifact.model_id}"
                )
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
