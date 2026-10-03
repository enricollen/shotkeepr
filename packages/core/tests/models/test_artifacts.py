import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from filelock import Timeout

from shotkeepr.core.adapters.models import artifacts
from shotkeepr.core.adapters.models.artifacts import MAX_REDIRECTS, VerifiedModelStore
from shotkeepr.core.application.models import ModelRegistry
from shotkeepr.core.domain.models.model import (
    InvalidModelManifestError,
    ModelArtifact,
    ModelDownloadError,
    ModelError,
    ModelIntegrityError,
    ModelManifest,
)


def test_streamed_download_integrity_cache_record_and_offline_reuse(
    model: tuple[ModelArtifact, bytes],
    tmp_path: Path,
) -> None:
    artifact, weights = model
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, content=weights)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        store = VerifiedModelStore(tmp_path, client=client)
        registry = ModelRegistry(ModelManifest((artifact,)), store)
        progress: list[tuple[int, int]] = []
        path = registry.fetch(artifact.model_id, progress=lambda a, b: progress.append((a, b)))
        assert path.read_bytes() == weights
        assert path == registry.verify(artifact.model_id)
        assert path == registry.fetch(artifact.model_id)
        assert len(calls) == 1
        assert progress[0] == (0, len(weights))
        assert progress[-1] == (len(weights), len(weights))
        record = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        assert record["license"] == "MIT"
        assert record["sha256"] == artifact.sha256
        assert record["version"] == artifact.version
        assert record["verified_at"]
        assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("mutation", ["short", "long", "hash"])
def test_bad_download_is_never_published(
    model: tuple[ModelArtifact, bytes],
    tmp_path: Path,
    mutation: str,
) -> None:
    artifact, weights = model
    content = {"short": weights[:-1], "long": weights + b"x", "hash": b"x" * len(weights)}[mutation]
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    ) as client:
        store = VerifiedModelStore(tmp_path, client=client)
        with pytest.raises(ModelIntegrityError):
            store.fetch(artifact)
    assert not list(tmp_path.rglob("*.onnx"))
    assert not list(tmp_path.rglob("*.part"))


def test_corrupted_cache_is_not_silently_replaced(
    model: tuple[ModelArtifact, bytes], tmp_path: Path
) -> None:
    artifact, weights = model
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=weights))
    ) as client:
        store = VerifiedModelStore(tmp_path, client=client)
        path = store.fetch(artifact)
        path.write_bytes(b"x" * len(weights))
        with pytest.raises(ModelIntegrityError, match="SHA-256"):
            store.verify(artifact)
        with pytest.raises(ModelIntegrityError):
            store.fetch(artifact)
        path.write_bytes(b"x")
        with pytest.raises(ModelIntegrityError, match="dimensione"):
            store.verify(artifact)


def test_missing_cache_does_not_create_directories(
    model: tuple[ModelArtifact, bytes], tmp_path: Path
) -> None:
    root = tmp_path / "absent"
    with pytest.raises(ModelError, match="non presenti"):
        VerifiedModelStore(root).verify(model[0])
    assert not root.exists()


@pytest.mark.parametrize(
    ("status", "headers"),
    [
        (404, {}),
        (204, {}),
        (302, {}),
        (200, {"content-encoding": "br"}),
    ],
)
def test_download_http_failures(
    model: tuple[ModelArtifact, bytes],
    tmp_path: Path,
    status: int,
    headers: dict[str, str],
) -> None:
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, headers=headers))
        ) as client,
        pytest.raises(ModelDownloadError),
    ):
        VerifiedModelStore(tmp_path, client=client).fetch(model[0])
    assert not list(tmp_path.rglob("*.onnx"))


@pytest.mark.parametrize(
    "destination", ["http://models.example.test/file", "https://127.0.0.1/file"]
)
def test_unsafe_redirect_is_never_followed(
    model: tuple[ModelArtifact, bytes],
    tmp_path: Path,
    destination: str,
) -> None:
    requests: list[httpx.Request] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"location": destination})

    with (
        httpx.Client(transport=httpx.MockTransport(redirect)) as client,
        pytest.raises(InvalidModelManifestError),
    ):
        VerifiedModelStore(tmp_path, client=client).fetch(model[0])
    assert len(requests) == 1


def test_bounded_safe_redirect(model: tuple[ModelArtifact, bytes], tmp_path: Path) -> None:
    artifact, weights = model

    def redirect(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/final":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, content=weights)

    with httpx.Client(transport=httpx.MockTransport(redirect)) as client:
        assert VerifiedModelStore(tmp_path, client=client).fetch(artifact).read_bytes() == weights
    requests: list[httpx.Request] = []

    def loop(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(307, headers={"location": "/loop"})

    with (
        httpx.Client(transport=httpx.MockTransport(loop)) as client,
        pytest.raises(ModelDownloadError, match="redirect"),
    ):
        VerifiedModelStore(tmp_path / "loop", client=client).fetch(artifact)
    assert len(requests) == MAX_REDIRECTS + 1


def test_stream_failure_cleans_partial_file(
    model: tuple[ModelArtifact, bytes], tmp_path: Path
) -> None:
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"partial"
            raise httpx.ReadError("connection lost")

    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=BrokenStream())
            )
        ) as client,
        pytest.raises(ModelDownloadError),
    ):
        VerifiedModelStore(tmp_path, client=client).fetch(model[0])
    assert not list(tmp_path.rglob("*.onnx"))
    assert not list(tmp_path.rglob("*.part"))


def test_concurrent_fetch_publishes_only_one_verified_download(
    model: tuple[ModelArtifact, bytes],
    tmp_path: Path,
) -> None:
    artifact, weights = model
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=weights)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:

        def fetch(_: int) -> Path:
            return VerifiedModelStore(tmp_path, client=client).fetch(artifact)

        with ThreadPoolExecutor(max_workers=4) as workers:
            paths = list(workers.map(fetch, range(4)))
    assert len(set(paths)) == 1
    assert len(requests) == 1
    assert paths[0].read_bytes() == weights


def test_versions_are_kept_separate(model: tuple[ModelArtifact, bytes], tmp_path: Path) -> None:
    artifact, weights = model
    other = replace(artifact, version="2.0.0")
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=weights))
    ) as client:
        store = VerifiedModelStore(tmp_path, client=client)
        assert store.fetch(artifact) != store.fetch(other)


def test_existing_empty_cache_reports_missing_weights(
    model: tuple[ModelArtifact, bytes],
    tmp_path: Path,
) -> None:
    artifact = model[0]
    (tmp_path / artifact.model_id / artifact.version).mkdir(parents=True)
    with pytest.raises(ModelError, match="non presenti"):
        VerifiedModelStore(tmp_path).verify(artifact)


def test_cache_symlink_cannot_escape_the_model_root(
    model: tuple[ModelArtifact, bytes],
    tmp_path: Path,
) -> None:
    root = tmp_path / "cache"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        (root / model[0].model_id).symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Collegamenti simbolici non disponibili: {exc}")
    with pytest.raises(ModelError, match="non sicuro"):
        VerifiedModelStore(root).fetch(model[0])
    assert list(outside.iterdir()) == []


def test_cache_lock_timeout_is_reported(
    model: tuple[ModelArtifact, bytes],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def occupied(path: str, *, timeout: int) -> None:
        raise Timeout(path)

    monkeypatch.setattr(artifacts, "FileLock", occupied)
    with pytest.raises(ModelError, match="occupata"):
        VerifiedModelStore(tmp_path).fetch(model[0])
    assert not list(tmp_path.rglob("*.onnx"))
