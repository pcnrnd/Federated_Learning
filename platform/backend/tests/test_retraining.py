"""재교육 intent의 원자성/재시작/동일성/실패 후행 차단. 원천은 fixture 사일로 안에만 둔다."""
import importlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from retraining_helpers import PRIVATE, clean_local, config_body, publish, setup_world
from test_ridge_artifacts import completed_result  # noqa: F401
from services import cleaning_job_service as cleaning, training_job_service as training
from services import distribution_service as ledger, model_registry, retraining_config as configs
from services import retraining_execution as execution, retraining_service as service
from storage.factory import reset_repositories
from models.federated_schemas import SiloGroupRequest
from datetime import datetime, timedelta


@pytest.fixture(params=["yaml", "sqlite"])
def world(request, monkeypatch, tmp_path, completed_result):
    monkeypatch.setenv("FED_STORAGE", request.param)
    reset_repositories()
    return setup_world(tmp_path, completed_result)


def command(world, **updates):
    config = configs.put_config(config_body(world))
    return dict(dict(retrain_config_id=config["retrain_config_id"], request_id="user-command"), **updates)


def advance_to_clean(world):
    event = service.create_manual(command(world))
    execution.advance(event["event_id"])
    execution.advance(event["event_id"])
    return service.get_event(event["event_id"])


def test_config_pins_actual_artifact_policy_topology_and_manual_is_idempotent(world):
    body = command(world)
    with ThreadPoolExecutor(max_workers=2) as pool:
        events = list(pool.map(lambda _: service.create_manual(body), range(2)))
    assert events[0] == events[1] and len(service.overview()["events"]) == 1
    config = service.overview()["configs"][0]["definition"]
    assert config["live_learning"]["initial_parameters"] == list(world.artifact.parameters)
    assert config["weights_sha256"] == world.artifact.weights_sha256
    assert service.get_event(events[0]["event_id"])["status"] == "queued"
    assert len(cleaning.list_jobs()) == 1 and training.list_jobs() == []
    changed = configs.put_config(config_body(world, max_rounds=3))
    with pytest.raises(HTTPException) as conflict:
        service.create_manual(dict(body, retrain_config_id=changed["retrain_config_id"]))
    assert conflict.value.status_code == 409
    assert service.create_manual(dict(body, retrain_config_id=changed["retrain_config_id"], request_id="new-command"))["event_id"] != events[0]["event_id"]


@pytest.mark.parametrize("boundary", ["event-before", "event-after", "intent-before", "intent-after"])
def test_failed_intent_save_cannot_authorize_child_even_same_process_retry_and_reload(world, monkeypatch, boundary):
    body = command(world)
    original = ledger._save
    failed = False
    def save(state):
        nonlocal failed
        events = list(state["retrain_events"].values())
        target = "queued" if boundary.startswith("event") else "cleaning_intent"
        if events and events[0]["status"] == target and not failed:
            failed = True
            if boundary.endswith("after"):
                original(state)
            raise OSError("injected durable boundary")
        return original(state)
    monkeypatch.setattr(ledger, "_save", save)
    if boundary.startswith("event"):
        with pytest.raises(OSError):
            service.create_manual(body)
        event = service.create_manual(body)
    else:
        event = service.create_manual(body)
        execution.advance(event["event_id"])
    assert failed and len(cleaning.list_jobs()) == 1
    service.create_manual(body)
    reset_repositories()
    importlib.reload(service)
    for _ in range(3):
        execution.advance(event["event_id"])
    assert len(cleaning.list_jobs()) == 2 and service.get_event(event["event_id"])["status"] == "wait_cleaning"


@pytest.mark.parametrize("child", ["cleaning", "training"])
def test_child_created_then_link_save_failure_reuses_exact_child_and_frozen_output(world, monkeypatch, child):
    event = service.create_manual(command(world))
    execution.advance(event["event_id"])
    if child == "training":
        execution.advance(event["event_id"])
        clean_local(world, event["cleaning_request"]["job_id"])
        execution.advance(event["event_id"])
    target = "wait_cleaning" if child == "cleaning" else "training"
    original = ledger._save
    failed = False
    def save(state):
        nonlocal failed
        if state["retrain_events"][event["event_id"]]["status"] == target and not failed:
            failed = True
            raise OSError("child exists, coordinator link missing")
        original(state)
    monkeypatch.setattr(ledger, "_save", save)
    execution.advance(event["event_id"])
    reset_repositories()
    execution.advance(event["event_id"])
    assert failed and len(cleaning.list_jobs()) == 2
    assert service.get_event(event["event_id"])["status"] == target
    assert len(training.list_jobs()) == (1 if child == "training" else 0)
    if child == "training":
        for directory in world.data.values():
            (directory / "input.json").unlink()
        execution.advance(event["event_id"])
        assert service.get_event(event["event_id"])["status"] == "training"


def test_pending_and_final_failed_cleaning_never_start_training(world, monkeypatch):
    event = advance_to_clean(world)
    execution.advance(event["event_id"])
    assert training.list_jobs() == []
    job = cleaning.get_job(event["cleaning_request"]["job_id"])
    monkeypatch.setattr(execution.cleaning, "get_job", lambda _identity: job.model_copy(update={"status": "failed"}))
    execution.advance(event["event_id"])
    assert service.get_event(event["event_id"])["error_code"] == "cleaning_failed"
    assert service.get_event(event["event_id"])["status"] == "failed" and training.list_jobs() == []


def test_occupied_child_id_must_match_exact_owner_payload(world):
    event = service.create_manual(command(world))
    other = dict(event["cleaning_request"], dataset_label="different")
    from models.cleaning_schemas import CleaningJobCreate
    cleaning.create_job(CleaningJobCreate(**other))
    execution.advance(event["event_id"])
    execution.advance(event["event_id"])
    assert service.get_event(event["event_id"])["error_code"] == "child_request_conflict"
    assert cleaning.get_job(other["job_id"]).dataset_label == "different" and training.list_jobs() == []


def test_base_reference_and_invalid_configuration_fail_closed_without_raw_state(world):
    configs.put_config(config_body(world))
    with pytest.raises(HTTPException) as referenced:
        model_registry.archive_model("model", "1.0.0")
    assert referenced.value.status_code == 409
    wrong = config_body(world, policy_id="a" * 64)
    with pytest.raises(HTTPException):
        configs.put_config(wrong)
    assert PRIVATE not in json.dumps(ledger._load())


def test_successful_output_cannot_be_rescheduled_during_training_and_topology_change_blocks_start(world):
    from services.cleaning_execution import reschedule
    from services import silo_group_service
    event = advance_to_clean(world)
    clean_local(world, event["cleaning_request"]["job_id"])
    execution.advance(event["event_id"])
    frozen = cleaning.get_job(event["cleaning_request"]["job_id"]).model_dump()
    with pytest.raises(HTTPException) as reserved:
        reschedule(frozen["job_id"], "2026-10-21T00:00:00+00:00")
    assert reserved.value.status_code == 409
    assert cleaning.get_job(frozen["job_id"]).model_dump() == frozen
    silo_group_service.update_group("retrain-group", SiloGroupRequest(group_id="retrain-group", member_node_ids=[world.nodes[0]]))
    execution.advance(event["event_id"])
    assert service.get_event(event["event_id"])["error_code"] == "topology_changed"
    assert training.list_jobs() == []


def test_missing_or_changed_base_weights_never_create_event_or_training(world):
    body = command(world)
    world.artifact.weights_path.write_text('{"corrupt":true}', encoding="utf-8")
    with pytest.raises(HTTPException) as corrupt:
        service.create_manual(body)
    assert corrupt.value.status_code == 409
    assert service.overview()["events"] == [] and training.list_jobs() == []


def test_reschedule_race_is_atomic_with_snapshot_reservation_and_terminal_jobs_remain_compatible(world, monkeypatch):
    from services.cleaning_execution import reschedule
    event = advance_to_clean(world)
    identity = event["event_id"]
    job_id = event["cleaning_request"]["job_id"]
    clean_local(world, job_id)
    entered, release, check = threading.Event(), threading.Event(), threading.Event()
    original_update, original_check = service.update, service.cleaning_reserved
    def update(event_id, **values):
        if values.get("status") == "training_intent":
            entered.set()
            assert release.wait(3)
        return original_update(event_id, **values)
    def reserved(*args):
        check.set()
        return original_check(*args)
    monkeypatch.setattr(service, "update", update)
    monkeypatch.setattr(service, "cleaning_reserved", reserved)
    with ThreadPoolExecutor(max_workers=2) as pool:
        freezing = pool.submit(execution.advance, identity)
        assert entered.wait(3)
        rescheduling = pool.submit(reschedule, job_id, "2026-10-21T00:00:00+00:00")
        assert not check.wait(.05)  # snapshot 읽기와 durable 예약 사이 job lock을 놓치지 않는다.
        release.set()
        freezing.result(timeout=3)
        with pytest.raises(HTTPException) as conflict:
            rescheduling.result(timeout=3)
        assert conflict.value.status_code == 409
    assert check.is_set() and cleaning.get_job(job_id).generation == 0
    service.update(identity, status="failed", resume_status="training_intent", error_code="test_terminal")
    assert reschedule(job_id, "2026-10-21T00:00:00+00:00").generation == 1
    assert reschedule("retrain-baseline", "2026-10-21T00:00:00+00:00").generation == 1


def test_reschedule_winning_before_snapshot_is_detected_and_never_trains_new_generation(world):
    from services.cleaning_execution import reschedule
    event = advance_to_clean(world)
    identity = event["event_id"]
    job_id = event["cleaning_request"]["job_id"]
    clean_local(world, job_id)
    reschedule(job_id, "2020-01-01T00:00:00+00:00")
    execution.advance(identity)
    assert service.get_event(identity)["status"] == "failed"
    assert service.get_event(identity)["error_code"] == "cleaning_generation_conflict"
    assert training.list_jobs() == []
    configs.put_config(config_body(world, enabled=False))
    assert model_registry.archive_model("model", "1.0.0").status == "archived"
    with pytest.raises(HTTPException) as blocked:
        service.retry(identity)
    assert blocked.value.status_code == 409


def test_API_ACK_loss_repeated_manual_request_returns_same_event_after_reload(world):
    from main import app
    body = command(world)
    with TestClient(app) as api:
        first = api.post("/api/monitoring/distributions/retraining/events", json=body)
        assert first.status_code == 202
        reset_repositories()
        second = api.post("/api/monitoring/distributions/retraining/events", json=body)
        assert second.status_code == 202 and second.json()["event_id"] == first.json()["event_id"]
        assert api.get("/api/monitoring/distributions/retraining").json()["events"][0]["event_id"] == first.json()["event_id"]


def test_critical_report_requires_explicit_auto_opt_in_and_duplicate_ticks_are_safe(world):
    from test_retraining_flow import change_local_source
    from models.cleaning_schemas import CleaningJobCreate
    configs.put_config(config_body(world))
    change_local_source(world)
    world.at = (datetime.fromisoformat(world.at) + timedelta(seconds=1)).isoformat()
    cleaning.create_job(CleaningJobCreate(job_id="critical-observation", recipe_name="retrain-recipe", recipe_version="1.0.0",
        group_id="retrain-group", dataset_label="input"))
    manifests = clean_local(world, "critical-observation")
    publish(world, "critical-observation", manifests)
    service.tick()
    assert service.overview()["events"] == []
    configs.put_config(config_body(world, auto_enabled=True))
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: service.tick(), range(2)))
    reset_repositories()
    service.tick()
    events = service.overview()["events"]
    assert len(events) == 1 and events[0]["automatic"] is True
    assert events[0]["drift_event_id"] is not None
    assert len(cleaning.list_jobs()) == 3  # 기준 관측 + 새 관측 + 단일 재교육 정제.
