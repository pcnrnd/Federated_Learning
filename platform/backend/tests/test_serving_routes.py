from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json

from fastapi import HTTPException
import pytest

from models.serving_schemas import ComparisonGate, ServingPredictRequest
from services import deployment_service, model_registry, serving_requests, serving_routes as routes, serving_store as store
from serving_helpers import setup
from storage.factory import reset_repositories
from test_ridge_artifacts import completed_result


@pytest.fixture(params=["yaml", "sqlite"])
def world(tmp_path, monkeypatch, request, completed_result):
    monkeypatch.setenv("FED_STORAGE", request.param)
    reset_repositories()
    value = setup(tmp_path, monkeypatch, completed_result)
    yield value
    value.resume.set()
    for http, thread in value.servers:
        http.shutdown(); http.server_close(); thread.join(3)
        assert not thread.is_alive()


def gate(**updates):
    values = dict(min_pairs=1, window_seconds=60, max_age_seconds=30, max_error_rate=0,
        max_mean_abs_difference=2.01, max_latency_ratio=None)
    values.update(updates)
    return ComparisonGate(**values)


def paired(gate_value=None):
    route = routes.ensure_route("primary")
    return routes.attach_shadow(route.route_id, "shadow-pair", "shadow", 100, gate_value)


def predict(route, identity="a"*32):
    return serving_requests.predict(route.route_id, ServingPredictRequest(inputs=[[1, 2, 3]], request_id=identity))


def test_real_paired_http_different_weights_and_route_promotion_rollback(world):
    route = paired(gate())
    first = predict(route)
    assert first["predictions"] == [13.0] and first["version"] == "1.0.0"
    delivered = [value for value in world.received if value["request_id"] == "a"*32]
    assert {value["version"] for value in delivered} == {"1.0.0", "1.0.1"}
    assert len({value["transient_input_hash"] for value in delivered}) == 1
    evidence = serving_requests.comparison(route.route_id)
    assert evidence.gate_ready and evidence.pairs == 1 and evidence.mean_abs_difference == 2
    for role in ("primary", "shadow"):
        assert evidence.paired_roles[role].requests == 1 and evidence.roles[role].measured_requests == 1
        assert evidence.paired_roles[role].mean_latency_ms > 0
        span = (datetime.fromisoformat(evidence.window_end)-datetime.fromisoformat(evidence.window_start)).total_seconds()
        assert evidence.roles[role].throughput_rps == pytest.approx(1/span)
    with ThreadPoolExecutor(max_workers=2) as pool:
        promoted = list(pool.map(lambda _i: routes.promote(route.route_id), range(2)))
    assert {value.generation for value in promoted} == {route.generation+1}
    assert predict(route, "b"*32)["predictions"] == [15.0]
    assert routes.get_route(route.route_id).previous_deployment_id == "primary"
    assert deployment_service.get_deployment("primary").status == "running"  # 복원용 standby이며 정리 완료가 아니다.
    assert routes.rollback(route.route_id).primary_deployment_id == "primary"
    assert predict(route, "c"*32)["predictions"] == [13.0]
    persisted = json.dumps(store.read())
    for forbidden in ('"inputs"', '"predictions"', '"targets"', '"rows"', '"features"'):
        assert forbidden not in persisted
    assert store.read()["requests"]["a"*32]["roles"]["shadow"]["request_id_echoed"]


@pytest.mark.parametrize("defect", ["missing", "insufficient", "difference", "stale", "shadow-error", "primary-error", "shape"])
def test_absent_insufficient_stale_error_or_difference_cannot_promote(world, monkeypatch, defect):
    policy = None if defect == "missing" else gate(min_pairs=2 if defect == "insufficient" else 1,
        max_mean_abs_difference=0 if defect == "difference" else 2.01)
    route = paired(policy)
    if defect == "shadow-error": world.faults["1.0.1"]["predict"] = True
    if defect == "primary-error": world.faults["1.0.0"]["predict"] = True
    if defect == "shape": world.faults["1.0.1"]["shape"] = True
    if defect == "primary-error":
        with pytest.raises(HTTPException): predict(route)
    else:
        predict(route)
    if defect == "stale":
        future = datetime.now(timezone.utc)+timedelta(seconds=31)
        assert not serving_requests.comparison(route.route_id, at=future).gate_ready
        # 승격 본체에도 같은 평가시각을 사용해 실제 gate 거부를 확인한다.
        original = serving_requests.comparison
        monkeypatch.setattr(serving_requests, "comparison", lambda identity, **kw: original(identity, at=future, **kw))
    with pytest.raises(HTTPException) as rejected:
        routes.promote(route.route_id)
    assert rejected.value.status_code == 409
    assert routes.get_route(route.route_id).primary_deployment_id == "primary"


def test_shadow_failure_preserves_real_primary_response_and_unmeasured_errors_are_not_zero_latency(world):
    route = paired(gate())
    shadow = deployment_service.get_deployment("shadow")
    deployment_service._save(shadow.model_copy(update={"status": "failed"}))
    response = predict(route)
    assert response["predictions"] == [13.0] and response["shadow_status"] == "error"
    stats = serving_requests.comparison(route.route_id)
    assert stats.roles["shadow"].errors == 1 and stats.roles["shadow"].mean_latency_ms is None
    assert not stats.gate_ready


@pytest.mark.parametrize("after_write", [False, True])
def test_route_switch_save_failure_and_same_process_retry_reload_are_truthful(world, monkeypatch, after_write):
    route = paired(gate())
    predict(route)
    original, fired = store.save, False
    def save(data):
        nonlocal fired
        if data["routes"][route.route_id]["status"] == "promoted" and not fired:
            fired = True
            if after_write: original(data)
            raise OSError("injected atomic switch boundary")
        original(data)
    monkeypatch.setattr(store, "save", save)
    with pytest.raises(OSError): routes.promote(route.route_id)
    assert routes.get_route(route.route_id).primary_deployment_id == ("shadow" if after_write else "primary")
    reset_repositories()
    assert routes.promote(route.route_id).primary_deployment_id == "shadow"
    assert predict(route, "b"*32)["version"] == "1.0.1"


def test_inflight_pin_concurrent_duplicate_close_cleanup_and_late_completion(world):
    route = paired(gate())
    world.faults["1.0.1"]["block"] = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(predict, route)
        try:
            assert world.entered.wait(2)
            with pytest.raises(HTTPException) as duplicate: predict(route)
            assert duplicate.value.status_code == 409
            closed = routes.close(route.route_id)
            assert closed.status == "closed" and closed.cleanup_pending
            assert set(closed.cleanup_deployment_ids) == {"primary", "shadow"}
        finally:
            world.resume.set()
        assert request.result(timeout=4)["predictions"] == [13.0]
    assert not routes.cleanup(route.route_id).cleanup_pending
    assert world.containers == {}


def test_restart_pending_is_interrupted_without_raw_replay_and_route_reference_wins_over_stale_status(world, monkeypatch):
    route = paired(gate())
    data = store.read()
    data["requests"]["d"*32] = dict(request_id="d"*32, route_id=route.route_id, generation=route.generation,
        owner_epoch="previous-process", started_at=store.now(), status="pending", input_count=1,
        primary_deployment_id="primary", shadow_deployment_id="shadow", roles={})
    store.save(data)
    recovered = store.read()["requests"]["d"*32]
    assert recovered["status"] == "interrupted" and recovered["comparison_error"] == "ServerRestart"
    assert not serving_requests.comparison(route.route_id).gate_ready
    with pytest.raises(HTTPException): predict(route, "d"*32)
    old = deployment_service.get_deployment("primary")
    deployment_service._save(old.model_copy(update={"status": "stopped", "container_map": {}}))
    for action in (model_registry.archive_model, model_registry.delete_model):
        with pytest.raises(HTTPException): action("model", "1.0.0")
    with pytest.raises(HTTPException): deployment_service.stop_deployment("shadow")


def test_corrupt_serving_state_fails_closed_and_cannot_drop_lifecycle_references(world):
    paired(gate())
    path = store._path()
    path.write_text("routes: [broken", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(HTTPException) as blocked: routes.ensure_route("primary")
    assert blocked.value.status_code == 503 and path.read_bytes() == before
    with pytest.raises(HTTPException): model_registry.archive_model("model", "1.0.0")


@pytest.mark.parametrize("boundary", ["reserve", "complete"])
def test_request_metadata_failure_never_replays_raw_or_fabricates_zero_latency(world, monkeypatch, boundary):
    route = paired(gate())
    original, fired = store.save, False
    def save(data):
        nonlocal fired
        event = data["requests"].get("a"*32)
        if event and not fired and event["status"] == ("pending" if boundary == "reserve" else "completed"):
            fired = True
            raise OSError("injected request metadata boundary")
        original(data)
    monkeypatch.setattr(store, "save", save)
    with pytest.raises(OSError): predict(route)
    if boundary == "reserve":
        assert world.received == [] and store.read()["requests"] == {}
    else:
        assert len(world.received) == 2
        monkeypatch.setattr(store, "PROCESS_EPOCH", "restarted-process")
        event = store.read()["requests"]["a"*32]
        assert event["status"] == "interrupted" and event["roles"] == {}
        assert serving_requests.comparison(route.route_id).roles["primary"].mean_latency_ms is None
