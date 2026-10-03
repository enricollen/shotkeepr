"""Modello sintetico per inferenza reale: nessun peso di terze parti."""

import hashlib

import onnx
import pytest
from onnx import TensorProto, helper

from shotkeepr.core.domain.models.model import ModelArtifact


@pytest.fixture
def model() -> tuple[ModelArtifact, bytes]:
    graph = helper.make_graph(
        [helper.make_node("Mul", ["input", "two"], ["output"])],
        "test-multiplier",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [2, 2])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [2, 2])],
        [helper.make_tensor("two", TensorProto.FLOAT, [], [2.0])],
    )
    weights = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)], ir_version=10)
    onnx.checker.check_model(weights)
    content = weights.SerializeToString()
    artifact = ModelArtifact(
        model_id="test-multiplier",
        version="1.0.0",
        url="https://models.example.test/test.onnx",
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        license="MIT",
        license_url="https://models.example.test/LICENSE",
        source_url="https://models.example.test/source",
    )
    return artifact, content
