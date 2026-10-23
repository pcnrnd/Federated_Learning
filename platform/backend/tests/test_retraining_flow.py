"""실제 로컬 정제→분포 경보→HTTP 두 라운드→새 가중치/추론 및 최종 연결 복구."""
import importlib
import json
from contextlib import ExitStack
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from config import settings
from models.cleaning_schemas import CleaningJobCreate
from retraining_helpers import PRIVATE, TARGET, clean_local, config_body, publish, setup_world
from test_live_training import central_http, serve
import test_ridge_artifacts as ridge_fixtures
from services import cleaning_job_service as cleaning, distribution_service as ledger
from services import distribution_drift, model_registry, retraining_config, retraining_service
from services import ridge_artifacts, training_job_service as jobs, training_model_service, training_round_service as rounds
from silo_sdk.cleaning_output import load_output
from silo_sdk.client import SiloClient
from silo_sdk.training_runtime import LiveWorker, make_server
from storage.factory import reset_repositories

# pytest가 수집할 동일 fixture 객체를 원래 이름으로 재노출한다.
completed_result = ridge_fixtures.completed_result


def independent_step(rows, base):
    errors = [sum(base[j] * float(row[f"x{j+1}"]) for j in range(3)) + base[-1] - float(row["y"]) for row in rows]
    gradients = [sum(error * float(row[f"x{j+1}"]) for row, error in zip(rows, errors)) / len(rows) + .001 * base[j] for j in range(3)]
    return [base[j] - .0001 * gradients[j] for j in range(3)] + [base[-1] - .0001 * sum(errors) / len(rows)]


def independent_loss(rows, parameters):
    errors = [sum(parameters[j] * float(row[f"x{j+1}"]) for j in range(3)) + parameters[-1] - float(row["y"]) for row in rows]
    return sum(error * error for error in errors) / (2 * len(rows)) + .001 * sum(p * p for p in parameters[:-1]) / 2


def change_local_source(world):
    path = world.data[world.nodes[0]] / "input.json"
    rows = json.loads(path.read_bytes())
    for row in rows:
        row["x1"] = str(float(row["x1"]) + 50)
    path.write_text(json.dumps(rows), encoding="utf-8")


def prepare_event(world, endpoints, automatic):
    config = retraining_config.put_config(config_body(world, worker_endpoints=endpoints, auto_enabled=automatic))
    change_local_source(world)
    if automatic:
        world.at = (datetime.fromisoformat(world.at) + timedelta(seconds=1)).isoformat()
        cleaning.create_job(CleaningJobCreate(job_id="observed-current", recipe_name="retrain-recipe", recipe_version="1.0.0",
            group_id="retrain-group", dataset_label="input"))
        manifests = clean_local(world, "observed-current")
        publish(world, "observed-current", manifests)
        assert any(e["severity"] == "critical" and e["state"] == "ready" for e in distribution_drift.overview()["items"])
    else:
        retraining_service.create_manual(dict(retrain_config_id=config["retrain_config_id"], request_id="real-manual"))
    retraining_service.tick()
    event = retraining_service.overview()["events"][0]
    retraining_service.tick()
    assert retraining_service.get_event(event["event_id"])["status"] == "wait_cleaning"
    manifests = clean_local(world, event["cleaning_request"]["job_id"])
    local = [row for node in world.nodes for row in load_output(str(world.data[node]), manifests[node])[0]]
    retraining_service.tick()
    retraining_service.tick()
    assert retraining_service.get_event(event["event_id"])["status"] == "training"
    return event, local


def execute_two_rounds(event, world, workers):
    base = list(world.artifact.parameters)
    last = None
    for _ in range(2):
        jobs.tick()
        entry = rounds.get_round(jobs.get_job(event["training_request"]["job_id"]).current_round_id)
        assert entry.base_parameters == base and entry.parent_round_id == last
        for node in world.roots:
            workers[node].process_round(entry.model_dump())
        for node in set(world.nodes) - set(world.roots):
            assert workers[node].process_round(entry.model_dump())
        for node in world.roots:
            assert workers[node].process_round(entry.model_dump())
        result = rounds.aggregate_round(entry.round_id)
        yield result, base
        base, last = result.parameters, result.round_id
    jobs.tick()


def inject_registration_failure(monkeypatch, mode):
    failed = []
    if mode == "yaml":
        original = ridge_artifacts.save_artifact
        def save(*args, **kwargs):
            if not failed:
                failed.append(True)
                raise OSError("artifact write failed")
            return original(*args, **kwargs)
        monkeypatch.setattr(ridge_artifacts, "save_artifact", save)
    else:
        original = model_registry.register_model
        def register(*args, **kwargs):
            entry = original(*args, **kwargs)
            if not failed:
                failed.append(True)
                raise OSError("registry write succeeded, response lost")
            return entry
        monkeypatch.setattr(model_registry, "register_model", register)
    return failed


@pytest.mark.parametrize("mode", ["yaml", "sqlite"])
@pytest.mark.parametrize("automatic", [False, True])
def test_local_to_new_model_real_HTTP_feedback_and_registration_link_recovery(tmp_path, monkeypatch, completed_result, mode, automatic):
    monkeypatch.setenv("FED_STORAGE", mode)
    reset_repositories()
    monkeypatch.setattr(settings, "API_KEY", None)
    world = setup_world(tmp_path, completed_result, hierarchy=automatic)
    monkeypatch.setattr(jobs.resource_service, "group_has_pressure", lambda _nodes: False)  # 자원 측정은 별도 G7 검증.
    with ExitStack() as stack:
        central = stack.enter_context(central_http())
        workers = {n: LiveWorker(SiloClient(central, n, retries=0, timeout=3), str(world.data[n])) for n in world.nodes}
        endpoints = {n: "http://127.0.0.1:9" for n in world.nodes}
        for node in world.roots:
            endpoints[node] = stack.enter_context(serve(make_server(workers[node], ("127.0.0.1", 0))))
        event, local_rows = prepare_event(world, endpoints, automatic)
        assert list(world.artifact.parameters) != [0.] * 4
        # 성공 정제 이후 원천 부재: worker는 frozen output만 소비한다.
        for directory in world.data.values():
            (directory / "input.json").unlink()
        for index, (result, base) in enumerate(execute_two_rounds(event, world, workers)):
            assert result.parameters == pytest.approx(independent_step(local_rows, base), abs=1e-9)
            assert result.total_samples == len(local_rows)
            assert len(result.origins) == len(world.nodes)
            if index == 0:
                intermediate = training_model_service.register_completed_result(result.round_id)
                with pytest.raises(HTTPException) as active_reference:
                    model_registry.archive_model(intermediate.name, intermediate.version)
                assert active_reference.value.status_code == 409
        retraining_service.tick()
        assert retraining_service.get_event(event["event_id"])["status"] == "wait_registration"
        write_failure = inject_registration_failure(monkeypatch, mode)
        retraining_service.tick()
        assert write_failure
        assert retraining_service.get_event(event["event_id"])["status"] == "wait_registration"
        assert retraining_service.get_event(event["event_id"])["registered_model"] is None
        original = ledger._save
        failed = False
        def save(state):
            nonlocal failed
            if state["retrain_events"][event["event_id"]]["status"] == "registered" and not failed:
                failed = True
                raise OSError("registry committed, event link lost")
            return original(state)
        monkeypatch.setattr(ledger, "_save", save)
        retraining_service.tick()
        linked = retraining_service.get_event(event["event_id"])
        assert failed and linked["status"] == "wait_registration"
        registered = [e for e in model_registry.list_models() if e.metadata.get("result_id") == linked["final_result_id"]]
        assert len(registered) == 1
        with pytest.raises(HTTPException) as reserved:
            model_registry.archive_model(registered[0].name, registered[0].version)
        assert reserved.value.status_code == 409
        reset_repositories()
        importlib.reload(retraining_service)
        retraining_service.tick()
        final = retraining_service.get_event(event["event_id"])
        assert final["status"] == "registered" and final["registered_model"]["version"] != "1.0.0"
        artifact = model_registry.get_ridge_artifact(model_registry.get_model("model", final["registered_model"]["version"]))
        assert list(artifact.parameters) == result.parameters
        assert independent_loss(local_rows, result.parameters) < independent_loss(local_rows, list(world.artifact.parameters))
        assert ridge_artifacts.predict(artifact, [[1., 2., 3.]]) == pytest.approx([sum(result.parameters[j] * (j+1) for j in range(3)) + result.parameters[-1]])
        from main import app
        with TestClient(app) as api:
            response = api.post("/api/models/predict", json={"name": "model", "version": final["registered_model"]["version"], "inputs": [[1., 2., 3.]]})
            assert response.status_code == 200
            assert response.json()["predictions"] == pytest.approx(ridge_artifacts.predict(artifact, [[1., 2., 3.]]))
            assert response.json()["weights_checksum"] == final["registered_model"]["weights_sha256"]
        from config.registry_manager import load_deployments
        assert load_deployments() == {}  # 모델 등록은 실제 운영 route 승격이 아니다.
        assert len([e for e in model_registry.list_models() if e.metadata.get("result_id") == final["final_result_id"]]) == 1
        central_text = json.dumps(ledger._load())
        assert PRIVATE not in central_text and str(TARGET) not in central_text and '"records"' not in central_text
        assert all(not (d / "input.json").exists() for d in world.data.values())
        assert len(retraining_service.overview()["events"]) == 1  # 같은 critical 관측을 다시 소비하지 않는다.
        assert final["automatic"] == automatic
