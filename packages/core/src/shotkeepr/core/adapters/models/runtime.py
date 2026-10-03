"""Sessioni ONNX tipizzate: accelerazione opzionale, CPU sempre disponibile."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType

import numpy as np
import numpy.typing as npt

from shotkeepr.core.domain.models.model import Device, ModelError

logger = logging.getLogger(__name__)
type Tensor = npt.NDArray[np.generic]
CPU = "CPUExecutionProvider"
CUDA = "CUDAExecutionProvider"
COREML = "CoreMLExecutionProvider"


def _runtime() -> ModuleType:
    try:
        return importlib.import_module("onnxruntime")
    except ModuleNotFoundError as exc:
        if exc.name != "onnxruntime":
            raise
        raise ModelError("installare shotkeepr-core[cpu] o shotkeepr-core[cuda]") from exc


def available_providers() -> tuple[str, ...]:
    return tuple(_runtime().get_available_providers())


def select_providers(available: Sequence[str], device: Device = Device.AUTO) -> tuple[str, ...]:
    if CPU not in available:
        raise ModelError("ONNX Runtime non offre il provider CPU obbligatorio")
    if device is Device.AUTO:
        primary = next(provider for provider in (CUDA, COREML, CPU) if provider in available)
    else:
        primary = {Device.CPU: CPU, Device.CUDA: CUDA, Device.COREML: COREML}[device]
        if primary not in available:
            raise ModelError(f"provider richiesto non disponibile: {primary}")
    return (primary,) if primary == CPU else (primary, CPU)


@dataclass(frozen=True, slots=True)
class RuntimeInfo:
    requested_device: str
    selected_provider: str
    active_providers: tuple[str, ...]
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class OnnxModelSession:
    def __init__(self, path: Path, *, device: Device = Device.AUTO, threads: int = 1) -> None:
        if not 1 <= threads <= 64:
            raise ValueError("threads deve essere compreso tra 1 e 64")
        runtime = _runtime()
        selected = select_providers(runtime.get_available_providers(), device)
        options = runtime.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = runtime.ExecutionMode.ORT_SEQUENTIAL
        errors = runtime.capi.onnxruntime_pybind11_state
        try:
            self._session = runtime.InferenceSession(
                str(path), sess_options=options, providers=list(selected)
            )
        except (
            errors.Fail,
            errors.InvalidArgument,
            errors.InvalidGraph,
            errors.InvalidProtobuf,
            errors.NoSuchFile,
            errors.NotImplemented,
            errors.RuntimeException,
        ) as exc:
            raise ModelError(f"modello ONNX non caricabile: {path.name}: {exc}") from exc
        self._session.disable_fallback()
        active: tuple[str, ...] = tuple(self._session.get_providers())
        if not active or active[0] not in {CPU, CUDA, COREML}:
            raise ModelError("ONNX Runtime non ha inizializzato un provider supportato")
        reason = None
        if active[0] != selected[0]:
            if device is not Device.AUTO:
                raise ModelError(f"il provider richiesto non si e' inizializzato: {selected[0]}")
            if CPU not in active:
                raise ModelError("nessun provider CPU disponibile dopo il degrado del runtime")
            reason = f"{selected[0]} non inizializzato; uso di {active[0]}"
            logger.warning("Degrado del runtime AI: %s", reason)
        self.info = RuntimeInfo(device.value, active[0], active, reason)
        self.input_names: tuple[str, ...] = tuple(item.name for item in self._session.get_inputs())
        self.output_names: tuple[str, ...] = tuple(
            item.name for item in self._session.get_outputs()
        )

    def run(self, inputs: Mapping[str, Tensor]) -> dict[str, Tensor]:
        if set(inputs) != set(self.input_names):
            raise ValueError(f"input richiesti dal modello: {', '.join(self.input_names)}")
        if any(not isinstance(value, np.ndarray) for value in inputs.values()):
            raise TypeError("gli input del modello devono essere array NumPy")
        outputs = self._session.run(list(self.output_names), dict(inputs))
        result: dict[str, Tensor] = {}
        for name, value in zip(self.output_names, outputs, strict=True):
            if not isinstance(value, np.ndarray):
                raise ModelError(f"output ONNX non tensoriale non supportato: {name}")
            result[name] = value
        return result
