"""G4-F1: 이미지 loader 단계의 실패 계약 및 설치된 framework의 실제 모델 로딩.

actual_optional_framework 사례는 실제 framework가 이미 설치돼야 하며 없으면 명시적으로 skip한다.
가벼운 mock 경계 통과를 실제 framework/컨테이너 검증으로 보고하지 않는다.
"""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from docker.errors import BuildError
from fastapi import HTTPException

from g4_helpers import completed_live_result
from models.packaging_schemas import ModelRegisterRequest, PackagingRequest
from services import model_registry, packaging_service as packaging, training_model_service


LOADER_STEP = 'RUN python -c "import inference_server; inference_server._load_model()"'


@pytest.mark.parametrize("framework", ["pytorch", "onnx", "tensorflow", "ridge"])
def test_build_runs_actual_image_loader_after_all_payload_copies(tmp_path, framework):
    if framework == "ridge":
        result = completed_live_result(tmp_path)
        entry = training_model_service.register_completed_result(result.round_id)
    else:
        weights = tmp_path / "source.weights"
        weights.write_bytes(b"opaque SDK-boundary fixture; not a valid framework model")
        entry = model_registry.register_model(ModelRegisterRequest(name="m", version="1.0.0",
            framework=framework, weights_path=str(weights)))
    context = tmp_path / "context"
    context.mkdir()
    packaging._prepare_build_context(entry, PackagingRequest(model_name=entry.name, version=entry.version), context)
    text = (context / "Dockerfile").read_text()
    assert text.index(LOADER_STEP) > text.rindex("COPY ")
    assert text.index(LOADER_STEP) < text.index("EXPOSE ")
    assert "except" not in text[text.index(LOADER_STEP):text.index(LOADER_STEP) + len(LOADER_STEP)]


@pytest.mark.parametrize("framework", ["pytorch", "onnx", "tensorflow"])
def test_image_loader_failure_is_persisted_failed_not_built(tmp_path, monkeypatch, framework):
    weights = tmp_path / "invalid.weights"
    weights.write_bytes(b"nonempty invalid model")
    entry = model_registry.register_model(ModelRegisterRequest(name="bad", version="1.0.0",
        framework=framework, weights_path=str(weights)))
    def image_build(**kwargs):
        assert LOADER_STEP in (Path(kwargs["path"]) / "Dockerfile").read_text()
        raise BuildError("actual image loader failed", build_log=[])
    monkeypatch.setattr(packaging.docker, "from_env", lambda: SimpleNamespace(
        images=SimpleNamespace(build=image_build), close=lambda: None))
    with pytest.raises(HTTPException):
        packaging.build_package(PackagingRequest(model_name=entry.name, version=entry.version))
    state = packaging.get_package(entry.name, entry.version)
    assert state.status == "failed" and state.built_at is None and state.image_digest is None


def make_actual_model(tmp_path, framework):
    if framework == "pytorch":
        torch = pytest.importorskip("torch")
        path = tmp_path / "valid.pt"
        layer = torch.nn.Linear(2, 1)
        with torch.no_grad():
            layer.weight.copy_(torch.tensor([[2.0, 3.0]]))
            layer.bias.copy_(torch.tensor([4.0]))
        torch.jit.trace(layer, torch.zeros(1, 2)).save(str(path))
    elif framework == "onnx":
        onnx = pytest.importorskip("onnx")
        pytest.importorskip("onnxruntime")
        path = tmp_path / "valid.onnx"
        tensor, helper = onnx.TensorProto, onnx.helper
        graph = helper.make_graph([helper.make_node("Gemm", ["X", "W", "B"], ["Y"])], "linear",
            [helper.make_tensor_value_info("X", tensor.FLOAT, [None, 2])],
            [helper.make_tensor_value_info("Y", tensor.FLOAT, [None, 1])],
            [helper.make_tensor("W", tensor.FLOAT, [2, 1], [2.0, 3.0]), helper.make_tensor("B", tensor.FLOAT, [1], [4.0])])
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
        model.ir_version = min(model.ir_version, 9)
        onnx.save(model, str(path))
    else:
        tf = pytest.importorskip("tensorflow")
        np = pytest.importorskip("numpy")
        path = tmp_path / "valid.keras"
        model = tf.keras.Sequential([tf.keras.layers.Input(shape=(2,)), tf.keras.layers.Dense(1)])
        model.set_weights([np.array([[2.0], [3.0]], dtype=np.float32), np.array([4.0], dtype=np.float32)])
        model.save(path)
    return path


def load_rendered(context, monkeypatch):
    for name in ("MODEL_NAME", "MODEL_VERSION", "MODEL_FRAMEWORK"):
        monkeypatch.delenv(name, raising=False)
    source = next((context / "weights").iterdir())
    monkeypatch.setenv("MODEL_PATH", str(source))
    monkeypatch.setenv("MODEL_META_PATH", str(context / "model_meta.json"))
    spec = importlib.util.spec_from_file_location("g4_framework_validation", context / "inference_server.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "g4_framework_validation", module)
    spec.loader.exec_module(module)
    return module


def flattened(values):
    return [number for value in values for number in (flattened(value) if isinstance(value, list) else [value])]


@pytest.mark.parametrize("framework", ["pytorch", "onnx", "tensorflow"])
def test_actual_optional_framework_small_valid_model_predicts_and_corrupt_bytes_cannot_build(tmp_path, monkeypatch, framework):
    weights = make_actual_model(tmp_path, framework)
    entry = model_registry.register_model(ModelRegisterRequest(name="valid", version="1.0.0",
        framework=framework, weights_path=str(weights)))
    seen = []
    def image_build(**kwargs):
        context = Path(kwargs["path"])
        assert LOADER_STEP in (context / "Dockerfile").read_text()
        module = load_rendered(context, monkeypatch)
        try:
            loaded = module._load_model()
        except Exception as exc:
            raise BuildError("framework loader rejected actual bytes", build_log=[]) from exc
        assert flattened(module._forward(loaded, [[1.0, 2.0]])) == pytest.approx([12.0])
        seen.append(True)
        return SimpleNamespace(id="sha256:" + "a"*64, attrs={"Size": 1}), iter([])
    monkeypatch.setattr(packaging.docker, "from_env", lambda: SimpleNamespace(
        images=SimpleNamespace(build=image_build), close=lambda: None))
    result = packaging.build_package(PackagingRequest(model_name=entry.name, version=entry.version))
    assert result.status == "built" and len(seen) == 1
    weights.write_bytes(b"nonempty corrupt model of wrong format")
    with pytest.raises(HTTPException):
        packaging.build_package(PackagingRequest(model_name=entry.name, version=entry.version))
    assert packaging.get_package(entry.name, entry.version).status == "failed"
