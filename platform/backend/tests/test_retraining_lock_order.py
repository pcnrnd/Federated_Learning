"""실제 정제/HTTP 학습 후 등록과 잡/직접 라운드 생성의 잠금 역전 회귀."""
import threading
from contextlib import ExitStack

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from config import settings
from models.federated_schemas import TrainingJobRequest
from retraining_helpers import setup_world
from test_live_training import central_http, serve
from test_retraining_flow import execute_two_rounds, prepare_event
import test_ridge_artifacts as ridge_fixtures
from services import model_registry, retraining_execution, retraining_service
from services import training_job_service as jobs, training_model_service as registration, training_round_service as rounds
from silo_sdk.client import SiloClient
from silo_sdk.training_runtime import LiveWorker, make_server
from storage.factory import reset_repositories

# pytest가 수집할 동일 fixture 객체를 원래 이름으로 재노출한다.
completed_result = ridge_fixtures.completed_result


class DeadlineLock:
    """오류 후보에서도 테스트 스레드를 영구 대기시키지 않는 시험 전용 잠금."""
    def __init__(self, lock):
        self.lock = lock

    def __enter__(self):
        if not self.lock.acquire(timeout=3):
            raise TimeoutError("test lock deadline exceeded")
        return self

    def __exit__(self, *_args):
        self.lock.release()


def concurrent_registration(event, world, monkeypatch, path):
    from main import app
    registration_entered = threading.Event()
    round_held = threading.Event()
    lookup_entered = threading.Event()
    original_register = registration.register_completed_result
    original_result = rounds.get_result
    original_model = rounds.get_model
    errors, results = [], {}
    for module, field in [(model_registry, "REGISTRY_LOCK"), (jobs, "_job_lock"), (rounds, "_round_lock")]:
        monkeypatch.setattr(module, field, DeadlineLock(getattr(module, field)))

    def register(*args, **kwargs):
        registration_entered.set()
        assert round_held.wait(3), "normal round did not reach model lookup"
        entry = original_register(*args, **kwargs)
        # 외부 registry lock을 풀어도 게시와 event 완료 사이의 영속 참조는 남아 있다.
        for action in [model_registry.archive_model, model_registry.delete_model]:
            with pytest.raises(HTTPException) as protected:
                action(entry.name, entry.version)
            assert protected.value.status_code == 409
        return entry

    def get_result(*args, **kwargs):
        if threading.current_thread().name == "retraining-register" and registration_entered.is_set():
            lookup_entered.set()
        return original_result(*args, **kwargs)

    def get_model(*args, **kwargs):
        round_held.set()
        assert lookup_entered.wait(3), "registration did not reach round lookup"
        return original_model(*args, **kwargs)

    monkeypatch.setattr(registration, "register_completed_result", register)
    monkeypatch.setattr(rounds, "get_result", get_result)
    monkeypatch.setattr(rounds, "get_model", get_model)

    def task_a():
        try:
            retraining_execution.advance(event["event_id"])
        except BaseException as exc:
            errors.append(exc)

    def task_b():
        try:
            assert registration_entered.wait(3)
            if path == "job-tick":
                results["opened"] = jobs.tick()
            else:
                api = TestClient(app)
                try:
                    response = api.post("/api/training-rounds", json={"model_name": "model", "version": "1.0.0",
                        "group_id": "retrain-group", "min_contributions": len(world.roots)})
                    assert response.status_code == 201, response.status_code
                    results["opened"] = [response.json()["round_id"]]
                finally:
                    api.close()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=task_a, name="retraining-register", daemon=True),
               threading.Thread(target=task_b, name="normal-flow", daemon=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads), "owned test threads did not finish"
    assert not errors, errors
    assert len(results["opened"]) == 1
    assert retraining_service.get_event(event["event_id"])["status"] == "registered"


@pytest.mark.parametrize("mode", ["yaml", "sqlite"])
@pytest.mark.parametrize("path", ["job-tick", "direct-round-api"])
def test_registration_and_public_round_creation_finish_without_lock_inversion(tmp_path, monkeypatch, completed_result, mode, path):
    monkeypatch.setenv("FED_STORAGE", mode)
    monkeypatch.setattr(settings, "API_KEY", None)
    reset_repositories()
    world = setup_world(tmp_path, completed_result)
    monkeypatch.setattr(jobs.resource_service, "group_has_pressure", lambda _nodes: False)
    with ExitStack() as stack:
        central = stack.enter_context(central_http())
        workers = {n: LiveWorker(SiloClient(central, n, retries=0, timeout=3), str(world.data[n])) for n in world.nodes}
        endpoints = {n: stack.enter_context(serve(make_server(workers[n], ("127.0.0.1", 0)))) for n in world.roots}
        event, _rows = prepare_event(world, endpoints, False)
        list(execute_two_rounds(event, world, workers))
        retraining_service.tick()
        event = retraining_service.get_event(event["event_id"])
        assert event["status"] == "wait_registration"
        if path == "job-tick":
            jobs.create_job(TrainingJobRequest(job_id="ordinary-concurrent", model_name="model", version="1.0.0",
                group_id="retrain-group", min_contributions=len(world.roots)))
        concurrent_registration(event, world, monkeypatch, path)
