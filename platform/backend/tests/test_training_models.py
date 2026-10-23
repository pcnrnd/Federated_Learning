"""실제 G3 결과→artifact→registry의 장애/재시작/삭제 경계. Docker는 실행하지 않는다."""
import importlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from config import settings
from config.registry_manager import save_deployments
from g4_helpers import completed_live_result
from models.packaging_schemas import ModelRegisterRequest
from services import model_registry as registry, ridge_artifacts
from services import training_model_service as registration


@pytest.fixture
def completed(tmp_path):
    return completed_live_result(tmp_path)


def registered_for(result_id):
    return [entry for entry in registry.list_models() if entry.metadata.get("result_id") == result_id]


def test_completed_round_scheduler_registers_once_and_actual_prediction_matches_independent_calculation(completed, monkeypatch):
    from services.round_scheduler import RoundScheduler
    RoundScheduler()._tick_blocking()
    entry = registered_for(completed.result_id)[0]
    assert entry.version == "1.0.1"
    assert entry.framework == "ridge"
    assert entry.metadata["result_id"] == completed.result_id
    actual = registry.predict_model(entry.name, entry.version, [[1.0, 2.0, 3.0]])
    expected = sum(w*x for w, x in zip(completed.parameters[:-1], [1.0, 2.0, 3.0])) + completed.parameters[-1]
    assert actual["predictions"] == pytest.approx([expected])
    before = entry.model_dump()
    importlib.reload(registration)
    assert registration.register_completed_result(completed.round_id).model_dump() == before
    assert len(registered_for(completed.result_id)) == 1
    assert registration.list_registrations()[0]["status"] == "registered"


def test_concurrent_completion_reserves_one_version(completed):
    with ThreadPoolExecutor(max_workers=4) as pool:
        entries = list(pool.map(lambda _: registration.register_completed_result(completed.round_id), range(8)))
    assert {entry.version for entry in entries} == {"1.0.1"}
    assert len(registered_for(completed.result_id)) == 1


@pytest.mark.parametrize("boundary", ["artifact", "registry", "completion_marker"])
def test_write_failure_and_restart_recover_same_reserved_model_version(completed, monkeypatch, boundary):
    if boundary == "artifact":
        original = ridge_artifacts.save_artifact
        def fail(*_args, **_kwargs):
            raise OSError("artifact publication injected failure")
        monkeypatch.setattr(ridge_artifacts, "save_artifact", fail)
    elif boundary == "registry":
        original = registry.save_models
        def fail(_models):
            raise OSError("registry write injected failure")
        monkeypatch.setattr(registry, "save_models", fail)
    else:
        original = registration._save
        def fail(states):
            if states[completed.result_id]["status"] == "registered":
                raise HTTPException(status_code=503, detail="completion marker injected failure")
            original(states)
        monkeypatch.setattr(registration, "_save", fail)
    with pytest.raises((OSError, HTTPException)):
        registration.register_completed_result(completed.round_id)
    if boundary == "artifact":
        monkeypatch.setattr(ridge_artifacts, "save_artifact", original)
    elif boundary == "registry":
        monkeypatch.setattr(registry, "save_models", original)
    importlib.reload(registration)
    recovered = registration.register_completed_result(completed.round_id)
    assert recovered.version == "1.0.1"
    assert len(registered_for(completed.result_id)) == 1
    assert registry.get_ridge_artifact(recovered).manifest["source_result"]["checksum"] == completed.checksum


def test_corrupt_registration_ledger_is_not_treated_as_empty(completed):
    path = registration._state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("- not-a-result-ledger\n")
    with pytest.raises(HTTPException) as failure:
        registration.register_completed_result(completed.round_id)
    assert failure.value.status_code == 503
    assert not registered_for(completed.result_id)


def test_explicit_conflicting_version_does_not_poison_result_reservation(completed):
    with pytest.raises(HTTPException) as conflict:
        registration.register_completed_result(completed.round_id, version="1.0.0")
    assert conflict.value.status_code == 409
    assert registration.list_registrations() == []
    assert registration.register_completed_result(completed.round_id).version == "1.0.1"


def test_api_predict_rejects_corrupt_weights_and_wrong_dimensions(completed, monkeypatch):
    from main import app
    monkeypatch.setattr(settings, "API_KEY", None)
    api = TestClient(app)
    response = api.post("/api/models/from-training", json={"round_id": completed.round_id})
    assert response.status_code == 201
    entry = registry.get_model("m", response.json()["version"])
    assert api.post(f"/api/models/m/{entry.version}/predict", json={"inputs": [[1, 2]]}).status_code == 422
    artifact = registry.get_ridge_artifact(entry)
    artifact.weights_path.write_bytes(b"corrupt")
    assert api.post(f"/api/models/m/{entry.version}/predict", json={"inputs": [[1, 2, 3]]}).status_code == 409
    with pytest.raises(HTTPException):
        registration.register_completed_result(completed.round_id)
    assert len(registered_for(completed.result_id)) == 1
    api.close()


def test_archive_delete_check_active_and_rollback_references_and_persist_deletion(completed):
    entry = registration.register_completed_result(completed.round_id)
    save_deployments({"previous": {"model_name": entry.name, "version": entry.version, "status": "stopped"},
        "current": {"model_name": entry.name, "version": "2.0.0", "status": "running", "previous_deployment_id": "previous"}})
    for action in (registry.archive_model, registry.delete_model):
        with pytest.raises(HTTPException) as reference:
            action(entry.name, entry.version)
        assert reference.value.status_code == 409
    save_deployments({})
    assert registry.archive_model(entry.name, entry.version).status == "archived"
    with pytest.raises(HTTPException):
        registry.predict_model(entry.name, entry.version, [[1, 2, 3]])
    weights = registry.get_ridge_artifact(entry).weights_path
    registry.delete_model(entry.name, entry.version)
    importlib.reload(registration)
    assert registration.reconcile_completed_results() == []
    assert registered_for(completed.result_id) == []
    assert weights.is_file()  # 기존 불변 파일을 registry 삭제와 함께 지우지 않는다.
    assert registration.list_registrations()[0]["status"] == "deleted"


def test_live_identity_actions_use_exact_json_name_without_path_collision(monkeypatch):
    from main import app
    monkeypatch.setattr(settings, "API_KEY", None)
    for name in ("기관/a:b", "기관%2Fa:b"):
        registry.register_model(ModelRegisterRequest(name=name, version="1.0.0", framework="pytorch", weights_path="/not-used"))
    api = TestClient(app)
    assert api.post("/api/models/archive", json={"name": "기관/a:b", "version": "1.0.0"}).json()["status"] == "archived"
    assert api.request("DELETE", "/api/models", json={"name": "기관/a:b", "version": "1.0.0"}).status_code == 200
    assert [entry.name for entry in registry.list_models()] == ["기관%2Fa:b"]
    api.close()
