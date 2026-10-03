import json
from dataclasses import replace
from pathlib import Path

import pytest

from shotkeepr.core.adapters.models.artifacts import load_manifest
from shotkeepr.core.domain.models.model import (
    CORE_LICENSES,
    InvalidModelManifestError,
    ModelArtifact,
    ModelError,
    ModelManifest,
)


def test_round_trip(model: tuple[ModelArtifact, bytes], tmp_path: Path) -> None:
    artifact, _ = model
    manifest = ModelManifest((artifact,))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
    assert load_manifest(path) == manifest
    assert manifest.select(artifact.model_id) == artifact
    assert manifest.select(artifact.model_id, artifact.version) == artifact


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("model_id", "../escape"),
        ("version", "../escape"),
        ("model_id", ""),
        ("sha256", "a" * 63),
        ("sha256", "A" * 64),
        ("sha256", "z" * 64),
        ("size_bytes", True),
        ("size_bytes", 0),
        ("size_bytes", -1),
        ("size_bytes", 1.5),
        ("license", "CC-BY-NC-4.0"),
        ("model_id", 1),
        ("url", None),
    ],
)
def test_rejects_invalid_metadata(
    model: tuple[ModelArtifact, bytes], key: str, value: object
) -> None:
    data = model[0].to_dict()
    data[key] = value
    with pytest.raises(InvalidModelManifestError):
        ModelArtifact.from_dict(data)


@pytest.mark.parametrize(
    "url",
    [
        "http://models.example.test/model.onnx",
        "file:///tmp/model.onnx",
        "https://localhost/model",
        "https://127.0.0.1/model",
        "https://10.0.0.1/model",
        "https://model.local/model",
        "https://a.internal/model",
        "https://a.localhost/model",
        "https://a.example.test:8443/model",
        "https://a.example.test:bad/model",
        "https://a.example.test/model?token=secret",
        "https://user:password@a.example.test/model",
        "https://a.example.test/model#fragment",
    ],
)
def test_rejects_unsafe_urls(model: tuple[ModelArtifact, bytes], url: str) -> None:
    data = model[0].to_dict()
    data["url"] = url
    with pytest.raises(InvalidModelManifestError):
        ModelArtifact.from_dict(data)


def test_rejects_unknown_missing_and_duplicate_fields(model: tuple[ModelArtifact, bytes]) -> None:
    data = model[0].to_dict()
    with pytest.raises(InvalidModelManifestError):
        ModelArtifact.from_dict({**data, "extra": 1})
    del data["license_url"]
    with pytest.raises(InvalidModelManifestError):
        ModelArtifact.from_dict(data)
    with pytest.raises(InvalidModelManifestError, match="duplicata"):
        ModelManifest((model[0], model[0]))


def test_multiple_versions_require_explicit_choice(model: tuple[ModelArtifact, bytes]) -> None:
    artifact = model[0]
    other = replace(artifact, version="2.0.0")
    manifest = ModelManifest((artifact, other))
    with pytest.raises(ModelError, match="--version"):
        manifest.select(artifact.model_id)
    with pytest.raises(ModelError, match="non presente"):
        manifest.select("missing")
    assert manifest.select(artifact.model_id, "2.0.0") == other


@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        {"schema_version": 2, "models": []},
        {"schema_version": True, "models": []},
        {"schema_version": 1, "models": {}},
        {"schema_version": 1, "models": [False]},
    ],
)
def test_rejects_malformed_manifest(tmp_path: Path, data: object) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(InvalidModelManifestError):
        load_manifest(path)


def test_rejects_repeated_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text('{"schema_version": 1, "models": [], "models": []}', encoding="utf-8")
    with pytest.raises(InvalidModelManifestError, match="duplicato"):
        load_manifest(path)


def test_repository_manifest_and_schema_agree() -> None:
    root = Path(__file__).resolve().parents[4] / "models"
    assert load_manifest(root / "manifest.json") == ModelManifest(())
    schema = json.loads((root / "manifest.schema.json").read_text(encoding="utf-8"))
    assert (
        set(schema["properties"]["models"]["items"]["properties"]["license"]["enum"])
        == CORE_LICENSES
    )
