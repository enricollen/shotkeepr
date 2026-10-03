import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from shotkeepr.core.__main__ import main
from shotkeepr.core.adapters.models import cli
from shotkeepr.core.adapters.models.artifacts import VerifiedModelStore
from shotkeepr.core.domain.models.model import ModelArtifact, ModelManifest


def test_list_approved_models_without_creating_cache(
    model: tuple[ModelArtifact, bytes],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = ModelManifest((model[0],))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
    cache = tmp_path / "cache"
    assert main(["models", "list", "--manifest", str(path), "--cache-dir", str(cache)]) == 0
    assert json.loads(capsys.readouterr().out) == manifest.to_dict()
    assert not cache.exists()


def test_model_cli_fetch_offline_verify_and_runtime_validation(
    model: tuple[ModelArtifact, bytes],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, weights = model
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(ModelManifest((artifact,)).to_dict()), encoding="utf-8")
    arguments = [artifact.model_id, "--manifest", str(path), "--cache-dir", str(tmp_path / "cache")]
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=weights))
    ) as client:
        monkeypatch.setattr(
            cli, "VerifiedModelStore", lambda root: VerifiedModelStore(root, client=client)
        )
        assert main(["models", "fetch", *arguments]) == 0
        capture = capsys.readouterr()
        result = json.loads(capture.out)
        assert result["verified"] is True
        assert "byte" in capture.err
    assert main(["models", "verify", *arguments]) == 0
    assert json.loads(capsys.readouterr().out)["verified"] is True
    assert main(["models", "validate", *arguments, "--device", "cpu"]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["runtime"]["selected_provider"] == "CPUExecutionProvider"
    assert validated["inputs"] == ["input"]
    Path(result["path"]).write_bytes(b"broken")
    assert main(["models", "verify", *arguments]) == 1
    assert "Modello non disponibile:" in capsys.readouterr().err


def test_providers_diagnostic_is_explicitly_not_a_session(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["models", "providers", "--device", "cpu"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["preferred_providers"] == ["CPUExecutionProvider"]
    assert result["initialized"] is False


def test_cli_reports_missing_manifest_and_unknown_model(
    model: tuple[ModelArtifact, bytes],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "manifest.json"
    assert main(["models", "list", "--manifest", str(path)]) == 1
    assert "Modello non disponibile:" in capsys.readouterr().err
    path.write_text(json.dumps(ModelManifest((model[0],)).to_dict()), encoding="utf-8")
    assert main(["models", "fetch", "missing", "--manifest", str(path)]) == 1
    assert "non presente" in capsys.readouterr().err


def test_cli_requires_a_version_if_multiple_are_declared(
    model: tuple[ModelArtifact, bytes],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact = model[0]
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(ModelManifest((artifact, replace(artifact, version="2.0"))).to_dict()),
        encoding="utf-8",
    )
    assert main(["models", "verify", artifact.model_id, "--manifest", str(path)]) == 1
    assert "--version" in capsys.readouterr().err


def test_cli_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["models"])
    assert exc.value.code == 2
