"""G5-A-F4: output-head와 batch 축을 구분한다. U와 선택적 실제 ONNX I를 분리."""
from types import SimpleNamespace
import sys

from fastapi.testclient import TestClient
import pytest

from models.packaging_schemas import DeploymentEntry, DeploymentRequest, ModelRegisterRequest, PackagingRequest
from services import deployment_runtime, model_registry, packaging_service
from test_package_loader_validation import load_rendered, make_actual_model


def rendered(tmp_path, monkeypatch, actual=False):
    weights = make_actual_model(tmp_path, "onnx") if actual else tmp_path / "fixture.onnx"
    if not actual:
        weights.write_bytes(b"loader boundary fixture")
    model = model_registry.register_model(ModelRegisterRequest(name="batch", version="1.0.0", framework="onnx", weights_path=str(weights)))
    context = tmp_path / "image-context"
    context.mkdir()
    packaging_service._prepare_build_context(model, PackagingRequest(model_name=model.name, version=model.version), context)
    return model, load_rendered(context, monkeypatch)


@pytest.mark.parametrize("rows", [1, 2, 3])
def test_F4_single_output_tensor_becomes_exact_batch_predictions_U(tmp_path, monkeypatch, rows):
    _model, module = rendered(tmp_path, monkeypatch)
    expected = [[12+10*index] for index in range(rows)]
    assert module._onnx_batch([SimpleNamespace(tolist=lambda: expected)], rows) == expected
    for outputs in ([], [SimpleNamespace(tolist=lambda: expected)]*2,
                    [SimpleNamespace(tolist=lambda: expected[:-1])], [SimpleNamespace(tolist=lambda: [[float("nan")]]*rows)]):
        with pytest.raises((ValueError, TypeError)):
            module._onnx_batch(outputs, rows)


def test_F4_multiple_model_outputs_rejected_before_cache_or_build_success_U(tmp_path, monkeypatch):
    _model, module = rendered(tmp_path, monkeypatch)
    session = SimpleNamespace(get_inputs=lambda: [object()], get_outputs=lambda: [object(), object()])
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=lambda _path: session))
    with pytest.raises(ValueError):
        module._load_model()
    assert module._model is None


@pytest.mark.parametrize("rows", [1, 2, 3])
def test_actual_optional_framework_onnx_batch_server_and_runtime_I(tmp_path, monkeypatch, rows):
    model, module = rendered(tmp_path, monkeypatch, actual=True)
    inputs = [[1.0+2*i, 2.0+2*i] for i in range(rows)]
    expected = [[12.0+10*i] for i in range(rows)]
    api = TestClient(module.app)
    result = api.post("/predict", json={"inputs": inputs, "request_id": "f"*32})
    assert result.status_code == 200 and result.json()["predictions"] == expected
    assert result.json()["request_id"] == "f"*32
    health = api.get("/health").json()
    identity = {key: health[key] for key in ("model", "version", "framework", "weights_checksum")}
    entry = DeploymentEntry(deployment_id="onnx-batch", model_name=model.name, version=model.version,
        image_tag="sha256:test", strategy="realtime", target_node_ids=["silo-1"], status="pending", created_at="now",
        expected_image_id="sha256:test", expected_identity=identity)
    container = SimpleNamespace(id="fixture", image=SimpleNamespace(id="sha256:test"), status="running", reload=lambda: None,
        attrs={"NetworkSettings": {"Ports": {"8501/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8501"}]}}})
    def http(url, body=None):
        return api.get("/health").json() if body is None else api.post("/predict", json=body).json()
    monkeypatch.setattr(deployment_runtime, "_json_request", http)
    request = DeploymentRequest(model_name=model.name, version=model.version, strategy="realtime",
        target_node_ids=["silo-1"], probe_inputs=inputs)
    assert deployment_runtime.verify_target(None, container, {}, entry, model, request).status == "running"
    api.close()
