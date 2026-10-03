from pathlib import Path

import numpy as np
import onnxruntime as ort
import pytest

from shotkeepr.core.adapters.models import runtime
from shotkeepr.core.adapters.models.runtime import (
    COREML,
    CPU,
    CUDA,
    OnnxModelSession,
    select_providers,
)
from shotkeepr.core.domain.models.model import Device, ModelArtifact, ModelError


@pytest.fixture
def model_path(model: tuple[ModelArtifact, bytes], tmp_path: Path) -> Path:
    path = tmp_path / "model.onnx"
    path.write_bytes(model[1])
    return path


@pytest.mark.parametrize(
    ("available", "device", "expected"),
    [
        ([CPU], Device.AUTO, (CPU,)),
        ([COREML, CPU], Device.AUTO, (COREML, CPU)),
        ([CUDA, COREML, CPU], Device.AUTO, (CUDA, CPU)),
        ([CUDA, CPU], Device.CPU, (CPU,)),
        ([COREML, CPU], Device.COREML, (COREML, CPU)),
        ([CUDA, CPU], Device.CUDA, (CUDA, CPU)),
        (["AzureExecutionProvider", CPU], Device.AUTO, (CPU,)),
    ],
)
def test_provider_selection(
    available: list[str], device: Device, expected: tuple[str, ...]
) -> None:
    assert select_providers(available, device) == expected


@pytest.mark.parametrize(
    ("available", "device"),
    [
        ([], Device.AUTO),
        ([CUDA], Device.AUTO),
        ([CPU], Device.CUDA),
        ([CPU], Device.COREML),
    ],
)
def test_explicit_missing_provider_never_silently_falls_back(
    available: list[str], device: Device
) -> None:
    with pytest.raises(ModelError):
        select_providers(available, device)


def test_real_cpu_inference(model_path: Path) -> None:
    session = OnnxModelSession(model_path, device=Device.CPU)
    values = np.array([[1, 2], [3, 4]], dtype=np.float32)
    output = session.run({"input": values})
    np.testing.assert_allclose(output["output"], values * 2, rtol=1e-6)
    assert session.input_names == ("input",)
    assert session.output_names == ("output",)
    assert session.info.selected_provider == CPU
    assert session.info.fallback_reason is None
    assert session.info.to_dict()["requested_device"] == "cpu"


def test_runtime_rejects_missing_input_and_non_tensor(model_path: Path) -> None:
    session = OnnxModelSession(model_path)
    with pytest.raises(ValueError, match="input"):
        session.run({})
    with pytest.raises(TypeError, match="NumPy"):
        session.run({"input": [1, 2]})


def test_non_tensor_output_is_not_silently_accepted(
    model_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = OnnxModelSession(model_path)
    monkeypatch.setattr(session._session, "run", lambda names, values: ["invalid"])
    with pytest.raises(ModelError, match="non tensoriale"):
        session.run({"input": np.zeros((2, 2), dtype=np.float32)})


@pytest.mark.parametrize("device", [Device.AUTO, Device.CUDA])
def test_accelerator_initialization_failure_is_reported(
    model_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    device: Device,
) -> None:
    constructor = ort.InferenceSession
    monkeypatch.setattr(ort, "get_available_providers", lambda: [CUDA, CPU])

    def cpu_only(path: str, *, sess_options: object, providers: list[str]):
        assert providers == [CUDA, CPU]
        return constructor(path, sess_options=sess_options, providers=[CPU])

    monkeypatch.setattr(ort, "InferenceSession", cpu_only)
    if device is Device.AUTO:
        session = OnnxModelSession(model_path)
        assert session.info.fallback_reason
        assert session.info.selected_provider == CPU
        assert "Degrado del runtime AI" in caplog.text
    else:
        with pytest.raises(ModelError, match="non si e' inizializzato"):
            OnnxModelSession(model_path, device=device)


def test_unsupported_active_provider_is_rejected(
    model_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    constructor = ort.InferenceSession

    def unsupported(path: str, *, sess_options: object, providers: list[str]):
        session = constructor(path, sess_options=sess_options, providers=[CPU])
        monkeypatch.setattr(session, "get_providers", lambda: ["UnknownExecutionProvider"])
        return session

    monkeypatch.setattr(ort, "InferenceSession", unsupported)
    with pytest.raises(ModelError, match="supportato"):
        OnnxModelSession(model_path)


@pytest.mark.parametrize("threads", [0, -1, 65])
def test_invalid_worker_count(model_path: Path, threads: int) -> None:
    with pytest.raises(ValueError, match="threads"):
        OnnxModelSession(model_path, threads=threads)


def test_invalid_graph_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "invalid.onnx"
    path.write_bytes(b"not an ONNX graph")
    with pytest.raises(ModelError, match="non caricabile"):
        OnnxModelSession(path)


def test_optional_runtime_dependency_failure_is_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str):
        raise ModuleNotFoundError("missing", name="onnxruntime")

    monkeypatch.setattr(runtime.importlib, "import_module", missing)
    with pytest.raises(ModelError, match=r"shotkeepr-core\[cpu\]"):
        runtime.available_providers()


def test_unrelated_import_failure_is_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str):
        raise ModuleNotFoundError("missing", name="other_dependency")

    monkeypatch.setattr(runtime.importlib, "import_module", missing)
    with pytest.raises(ModuleNotFoundError):
        runtime.available_providers()
