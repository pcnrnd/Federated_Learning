"""실제 렌더/복사한 독립 ridge 서버와 Docker 경계의 상태 검증. Docker 기동은 없다."""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from docker.errors import DockerException
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from g4_helpers import completed_live_result
from models.packaging_schemas import PackagingRequest
from services import model_registry as registry, packaging_service as packaging, training_model_service as registration


@pytest.fixture
def model(tmp_path):
    result = completed_live_result(tmp_path)
    entry = registration.register_completed_result(result.round_id)
    yield entry
    packaging._ACTIVE_BUILDS.clear()


def image_for(entry):
    return SimpleNamespace(id="sha256:" + "a" * 64, attrs={"Size": 123,
        "Config": {"Labels": {"fed.artifact_id": entry.metadata["artifact_id"],
            "fed.manifest_checksum": entry.metadata["manifest_sha256"],
            "fed.weights_checksum": entry.metadata["weights_sha256"]}}})


def prepared_server(tmp_path, model, monkeypatch):
    context = tmp_path / "image-context"
    context.mkdir()
    packaging._prepare_build_context(model, PackagingRequest(model_name=model.name, version=model.version), context)
    assert (context / "ridge_artifacts.py").is_file()
    monkeypatch.syspath_prepend(str(context))
    monkeypatch.delitem(sys.modules, "ridge_artifacts", raising=False)
    for name in ("MODEL_NAME", "MODEL_VERSION", "MODEL_FRAMEWORK", "MODEL_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARTIFACT_ROOT", str(context / "artifacts"))
    monkeypatch.setenv("MODEL_META_PATH", str(context / "model_meta.json"))
    spec = importlib.util.spec_from_file_location("standalone_g4_inference", context / "inference_server.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "standalone_g4_inference", module)
    spec.loader.exec_module(module)
    return context, module, TestClient(module.app)


def test_rendered_server_is_self_contained_and_predicts_actual_weights(tmp_path, model, monkeypatch):
    context, _module, api = prepared_server(tmp_path, model, monkeypatch)
    health = api.get("/health")
    assert health.status_code == 200
    assert health.json()["artifact_id"] == model.metadata["artifact_id"]
    assert health.json()["weights_checksum"] == model.metadata["weights_sha256"]
    assert Path(sys.modules["ridge_artifacts"].__file__) == context / "ridge_artifacts.py"
    values = registry.get_ridge_artifact(model).parameters
    expected = values[0] + 2*values[1] + 3*values[2] + values[-1]
    result = api.post("/predict", json={"inputs": [[1, 2, 3]]})
    assert result.status_code == 200
    assert result.json()["predictions"] == pytest.approx([expected])
    assert "note" not in result.json()
    assert api.post("/predict", json={"inputs": [[1, 2]]}).status_code == 422
    (context / "artifacts" / model.metadata["artifact_id"] / "weights.json").write_bytes(b"corrupt")
    assert api.get("/health").status_code == 503
    assert api.post("/predict", json={"inputs": [[1, 2, 3]]}).status_code == 503
    api.close()


def test_rendered_server_rejects_model_identity_override(tmp_path, model, monkeypatch):
    _context, module, api = prepared_server(tmp_path, model, monkeypatch)
    module.MODEL_VERSION = "9.9.9"
    assert api.get("/health").status_code == 503
    api.close()


def test_package_record_has_real_build_digest_and_copied_weights_checksums(model, monkeypatch):
    seen = []
    def build(**kwargs):
        context = Path(kwargs["path"])
        descriptor = json.loads((context / "model_meta.json").read_text())
        assert descriptor["weights_checksum"] == model.metadata["weights_sha256"]
        assert (context / "artifacts" / model.metadata["artifact_id"] / "manifest.json").is_file()
        seen.append(kwargs)
        return image_for(model), iter([])
    client = SimpleNamespace(images=SimpleNamespace(build=build), close=lambda: None)
    monkeypatch.setattr(packaging.docker, "from_env", lambda: client)
    result = packaging.build_package(PackagingRequest(model_name=model.name, version=model.version))
    assert len(seen) == 1
    assert result.image_digest == "sha256:" + "a" * 64
    record = packaging.get_package(model.name, model.version)
    assert record.status == "built"
    assert record.artifact_id == model.metadata["artifact_id"]
    assert record.weights_checksum == model.metadata["weights_sha256"]
    assert registry.get_model(model.name, model.version).package.model_dump() == record.model_dump()


@pytest.mark.parametrize("failure", ["docker", "image_identity"])
def test_failed_build_is_persisted_and_does_not_look_built(model, monkeypatch, failure):
    def build(**_kwargs):
        if failure == "docker":
            raise DockerException("injected build failure")
        image = image_for(model)
        image.attrs["Config"]["Labels"]["fed.weights_checksum"] = "0" * 64
        return image, iter([])
    monkeypatch.setattr(packaging.docker, "from_env", lambda: SimpleNamespace(images=SimpleNamespace(build=build), close=lambda: None))
    with pytest.raises(HTTPException):
        packaging.build_package(PackagingRequest(model_name=model.name, version=model.version))
    assert packaging.get_package(model.name, model.version).status == "failed"
    assert not packaging._ACTIVE_BUILDS


def test_no_weights_placeholder_or_docker_call_on_missing_artifact(model, monkeypatch):
    artifact = registry.get_ridge_artifact(model)
    artifact.weights_path.unlink()
    def forbidden():
        raise AssertionError("Docker must not be contacted")
    monkeypatch.setattr(packaging.docker, "from_env", forbidden)
    with pytest.raises(HTTPException) as failure:
        packaging.build_package(PackagingRequest(model_name=model.name, version=model.version))
    assert failure.value.status_code == 409
    assert packaging.get_package(model.name, model.version).status == "unbuilt"


def test_duplicate_build_is_rejected_and_restart_state_is_unknown(model, monkeypatch):
    tasks = BackgroundTasks()
    request = PackagingRequest(model_name=model.name, version=model.version)
    first = packaging.request_build(request, tasks)
    assert first.status == "building" and len(tasks.tasks) == 1
    with pytest.raises(HTTPException) as duplicate:
        packaging.request_build(request, BackgroundTasks())
    assert duplicate.value.status_code == 409
    monkeypatch.setattr(packaging, "_INSTANCE", "new-process")
    record = packaging.get_package(model.name, model.version)
    assert record.status == "unknown"
    assert record.image_digest is None and record.built_at is None
