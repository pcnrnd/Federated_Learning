"""실제 loopback HTTP + 불변 ridge 파일로 health/예측 검증. Docker 전송만 경계 대역."""
import hashlib
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from docker.errors import ImageNotFound

from g5_helpers import IMAGE
from models.packaging_schemas import DeploymentEntry, DeploymentRequest
from services import deployment_runtime as runtime, ridge_artifacts
import test_ridge_artifacts as ridge_fixtures

# pytest가 수집할 동일 fixture 객체를 원래 이름으로 재노출한다.
completed_result = ridge_fixtures.completed_result


@contextmanager
def endpoint(artifact, identity, defect=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def answer(self, value):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def do_GET(self):
            actual = {**identity, "version": "wrong"} if defect == "identity" else identity
            self.answer(dict(status="ok", **actual))

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            values = ridge_artifacts.predict(artifact, body["inputs"])
            if defect == "weights":
                values[0] += 1
            if defect == "count":
                values = values[:-1]
            if defect == "nonfinite":
                values[0] = float("nan")
            self.answer(dict(ok=True, input_count=len(body["inputs"]), predictions=values, **identity))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        assert not thread.is_alive()


@pytest.fixture
def artifact_world(tmp_path, monkeypatch, completed_result):
    artifact = ridge_artifacts.save_artifact(tmp_path / "artifacts", completed_result)
    model = SimpleNamespace(name="model", version="1.0.0", framework="ridge",
        metadata={"features": list(artifact.features), "result_id": completed_result["result_id"]}, input_schema={})
    monkeypatch.setattr(runtime.model_registry, "get_ridge_artifact", lambda _model: artifact)
    identity = dict(model="model", version="1.0.0", framework="ridge", weights_checksum=artifact.weights_sha256,
        artifact_id=artifact.artifact_id, manifest_checksum=artifact.manifest_sha256, result_id=completed_result["result_id"])
    entry = DeploymentEntry(deployment_id="http-verified", model_name="model", version="1.0.0", image_tag=IMAGE,
        strategy="realtime", target_node_ids=["silo-1"], status="pending", created_at="2026-10-19T00:00:00Z",
        expected_image_id=IMAGE, expected_identity=identity)
    req = DeploymentRequest(model_name="model", version="1.0.0", strategy="realtime", target_node_ids=["silo-1"],
        inference_port=8600, probe_inputs=[[1, 2, 3], [-1, 0, 2]])
    return artifact, model, identity, entry, req


def container_for(port):
    return SimpleNamespace(id="actual-endpoint-fixture", image=SimpleNamespace(id=IMAGE), status="running",
        reload=lambda: None, attrs={"NetworkSettings": {"Ports": {"8600/tcp": [{"HostIp": "0.0.0.0", "HostPort": str(port)}]}}})


def test_real_http_predictions_match_independent_hand_calculation_and_record_actual_dynamic_port(artifact_world):
    artifact, model, identity, entry, req = artifact_world
    with endpoint(artifact, identity) as port:
        result = runtime.verify_target(None, container_for(port), {"base_url": "tcp://127.0.0.1:2375"}, entry, model, req)
    assert result.status == "running" and result.image_id == IMAGE and result.verified_at
    assert result.endpoint == f"http://127.0.0.1:{port}"  # 내부 8600과 구분한 실측 할당
    assert result.prediction_checksum == hashlib.sha256(b"[13.0,11.0]").hexdigest()
    assert result.weights_checksum == artifact.weights_sha256
    assert "predictions" not in result.model_dump() and req.inference_port == 8600


@pytest.mark.parametrize("defect", ["identity", "weights", "count", "nonfinite"])
def test_http_success_code_with_wrong_model_or_predictions_is_not_verified(artifact_world, defect):
    artifact, model, identity, entry, req = artifact_world
    with endpoint(artifact, identity, defect) as port:
        with pytest.raises(ValueError):
            runtime.verify_target(None, container_for(port), {"base_url": "tcp://127.0.0.1:2375"}, entry, model, req)


def test_missing_binding_wrong_image_and_unreachable_endpoint_cannot_be_success(artifact_world, monkeypatch):
    _artifact, model, _identity, entry, req = artifact_world
    container = container_for(1)
    container.attrs["NetworkSettings"]["Ports"] = {}
    with pytest.raises(ValueError):
        runtime.verify_target(None, container, {}, entry, model, req, timeout=0)
    def unavailable(*_args, **_kwargs):
        raise OSError("fixture endpoint unavailable")
    monkeypatch.setattr(runtime, "_json_request", unavailable)
    container = container_for(1)
    container.image.id = "sha256:other"
    with pytest.raises(ValueError):
        runtime.verify_target(None, container, {}, entry, model, req, timeout=0)
    with pytest.raises(TimeoutError):
        runtime.verify_target(None, container_for(1), {"base_url": "tcp://127.0.0.1:2375"}, entry, model, req, timeout=0)


def test_built_package_and_actual_registered_artifact_must_agree(artifact_world, monkeypatch):
    from services import packaging_service
    artifact, model, identity, _entry, req = artifact_world
    record = SimpleNamespace(status="built", image_digest=IMAGE, image_tag="model:tag", weights_checksum=artifact.weights_sha256,
        artifact_id=artifact.artifact_id, manifest_checksum=artifact.manifest_sha256)
    monkeypatch.setattr(packaging_service, "get_package", lambda *_args: record)
    assert runtime.pinned_package(model, req) == (IMAGE, identity)
    for field, value in (("status", "failed"), ("weights_checksum", "bad"), ("artifact_id", "bad"), ("manifest_checksum", "bad")):
        original = getattr(record, field)
        setattr(record, field, value)
        with pytest.raises(ValueError):
            runtime.pinned_package(model, req)
        setattr(record, field, original)


def test_image_transfer_streams_exact_id_and_checks_target_labels(monkeypatch):
    identity = {"weights_checksum": "b"*64}
    image = SimpleNamespace(id=IMAGE, attrs={"Config": {"Labels": {"fed.weights_checksum": "b"*64}}},
        save=lambda **_kw: iter((b"image-", b"stream")))
    closed, loaded = [], []
    central = SimpleNamespace(images=SimpleNamespace(get=lambda _id: image), close=lambda: closed.append(True))
    monkeypatch.setattr(runtime.docker, "from_env", lambda: central)
    def get(_id):
        assert _id == IMAGE
        if not loaded:
            raise ImageNotFound("fixture target missing")
        return image
    def load(payload, **_kw):
        loaded.append(payload.read())
        return iter(({"stream": "Loaded image"},))
    target = SimpleNamespace(images=SimpleNamespace(get=get), api=SimpleNamespace(load_image=load))
    assert runtime.ensure_image(target, IMAGE, identity).id == IMAGE
    assert loaded == [b"image-stream"] and closed == [True]
    image.attrs["Config"]["Labels"]["fed.weights_checksum"] = "other"
    with pytest.raises(ValueError):
        runtime.ensure_image(target, IMAGE, identity)
