"""A·B 테스트 서비스 단위 테스트"""
from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException

from g5_helpers import IMAGE, IDENTITY, setup_world
from models.maintenance_schemas import ABTestRequest
from models.monitoring_schemas import MetricIngest
from models.packaging_schemas import DeploymentRequest, ModelRegisterRequest
from models.serving_schemas import ComparisonGate, ServingPredictRequest
from services import (
    ab_test_service,
    deployment_runtime,
    deployment_service,
    metric_store,
    model_registry,
    serving_requests,
    serving_routes,
    shadow_deployment_service,
)


@pytest.fixture(autouse=True)
def _seed(tmp_path, monkeypatch):
    # 프레임워크/daemon/health만 명시적으로 대역화한다. AB·배포·route 서비스는 실제 구현이다.
    world = setup_world(tmp_path, monkeypatch)
    for v in ("1.0.0", "1.1.0"):
        model_registry.register_model(
            ModelRegisterRequest(
                name="alpha",
                version=v,
                framework="pytorch",
                weights_path=world.model.weights_path,
            )
        )
    monkeypatch.setattr(deployment_runtime, "pinned_package", lambda model, _request:
        (IMAGE, {**IDENTITY, "model": model.name, "version": model.version}))
    verify = deployment_runtime.verify_target

    def endpoint(*args, **kwargs):
        return verify(*args, **kwargs).model_copy(update={"endpoint": "http://fixture/"+args[3].deployment_id})

    monkeypatch.setattr(deployment_runtime, "verify_target", endpoint)


def _create_primary():
    return deployment_service.create_deployment(
        DeploymentRequest(
            model_name="alpha",
            version="1.0.0",
            strategy="realtime",
            target_node_ids=["silo-2"],
        )
    )


def _passing_comparison(test, monkeypatch):
    """알려진 전송 대역으로 같은 요청을 쌍으로 관측하고 실제 승격 gate를 통과시킨다."""
    shadow = shadow_deployment_service.get_shadow(test.shadow_id)
    route = serving_routes.configure_gate(shadow.route_id, ComparisonGate(min_pairs=1,
        window_seconds=60, max_age_seconds=30, max_error_rate=0, max_mean_abs_difference=0))
    delivered = []

    def predict(url, body):
        entry = deployment_service.get_deployment(url.rsplit("/", 2)[-2])
        delivered.append((entry.deployment_id, body["request_id"], tuple(map(tuple, body["inputs"]))))
        return dict(ok=True, input_count=len(body["inputs"]), predictions=[1.0],
            request_id=body["request_id"], **entry.expected_identity)

    monkeypatch.setattr(deployment_runtime, "_json_request", predict)
    identities = (f"{i:032x}" for i in range(1000))
    identity = next(value for value in identities if
        int(hashlib.sha256(value.encode()).hexdigest()[:8], 16)/2**32*100 < route.mirror_pct)
    serving_requests.predict(route.route_id, ServingPredictRequest(inputs=[[1.0]], request_id=identity))
    assert set(delivered) == {(test.control_deployment_id, identity, ((1.0,),)),
                              (test.treatment_deployment_id, identity, ((1.0,),))}
    assert len(delivered) == 2
    comparison = serving_requests.comparison(route.route_id)
    assert comparison.gate_ready and comparison.pairs == 1 and comparison.mean_abs_difference == 0
    return route.route_id


def _ab_request(primary_id: str) -> ABTestRequest:
    return ABTestRequest(
        test_id="t1",
        model_name="alpha",
        control_version="1.0.0",
        treatment_version="1.1.0",
        group_id="g1",
        primary_deployment_id=primary_id,
        metric="accuracy",
        min_samples_per_arm=3,
        higher_is_better=True,
        significance_threshold=2.0,
    )


def _push_metric(version: str, value: float, ts: str = "2026-05-14T00:00:00Z") -> None:
    metric_store.ingest(
        MetricIngest(
            node_id="silo-2",
            model_name="alpha",
            version=version,
            metric="accuracy",
            value=value,
            timestamp=ts,
        )
    )


@pytest.mark.unit
def test_create_test_creates_shadow_pair():
    primary = _create_primary()
    test = ab_test_service.create_test(_ab_request(primary.deployment_id))

    assert test.status == "running"
    assert test.control_deployment_id == primary.deployment_id
    assert test.treatment_deployment_id != primary.deployment_id
    assert test.shadow_id


@pytest.mark.unit
def test_evaluate_inconclusive_when_insufficient_samples():
    primary = _create_primary()
    ab_test_service.create_test(_ab_request(primary.deployment_id))
    _push_metric("1.0.0", 0.9)
    _push_metric("1.1.0", 0.7)

    result = ab_test_service.evaluate_test("t1")

    assert result.winner == "inconclusive"
    assert "표본 부족" in result.message


@pytest.mark.unit
def test_evaluate_picks_treatment_when_clearly_better():
    primary = _create_primary()
    ab_test_service.create_test(_ab_request(primary.deployment_id))
    # control 낮음, treatment 높음 — 큰 차이
    for v in (0.50, 0.51, 0.49, 0.50, 0.52):
        _push_metric("1.0.0", v)
    for v in (0.95, 0.96, 0.94, 0.95, 0.97):
        _push_metric("1.1.0", v)

    result = ab_test_service.evaluate_test("t1")

    assert result.winner == "treatment"
    assert result.significant is True
    assert result.treatment_mean > result.control_mean


@pytest.mark.unit
def test_evaluate_picks_control_when_higher_is_better_and_control_wins():
    primary = _create_primary()
    ab_test_service.create_test(_ab_request(primary.deployment_id))
    for v in (0.95, 0.96, 0.94, 0.95, 0.97):
        _push_metric("1.0.0", v)
    for v in (0.50, 0.51, 0.49, 0.50, 0.52):
        _push_metric("1.1.0", v)

    result = ab_test_service.evaluate_test("t1")

    assert result.winner == "control"


@pytest.mark.unit
def test_promote_treatment_winner_promotes_shadow(monkeypatch):
    primary = _create_primary()
    test = ab_test_service.create_test(_ab_request(primary.deployment_id))
    for v in (0.50, 0.51, 0.49, 0.50, 0.52):
        _push_metric("1.0.0", v)
    for v in (0.95, 0.96, 0.94, 0.95, 0.97):
        _push_metric("1.1.0", v)
    ab_test_service.evaluate_test("t1")

    route_id = _passing_comparison(test, monkeypatch)
    finalized = ab_test_service.promote_winner("t1")

    assert finalized.status == "promoted"
    route = serving_routes.get_route(route_id)
    assert route.primary_deployment_id == test.treatment_deployment_id
    assert route.previous_deployment_id == primary.deployment_id
    response = serving_requests.predict(route_id, ServingPredictRequest(inputs=[[1.0]], request_id="f"*32))
    assert response["deployment_id"] == test.treatment_deployment_id and response["version"] == "1.1.0"
    # 실제 요청 경로가 전환되고 이전 정상 실행은 route rollback용 standby로 보존된다.
    standby = deployment_service.get_deployment(primary.deployment_id)
    assert standby.status == "running" and standby.verified_at
    assert deployment_service.get_deployment(test.treatment_deployment_id).status == "running"
    assert serving_routes.rollback(route_id).primary_deployment_id == primary.deployment_id
    restored = serving_requests.predict(route_id, ServingPredictRequest(inputs=[[1.0]], request_id="e"*32))
    assert restored["deployment_id"] == primary.deployment_id and restored["version"] == "1.0.0"


@pytest.mark.unit
def test_promote_control_winner_aborts_shadow():
    primary = _create_primary()
    test = ab_test_service.create_test(_ab_request(primary.deployment_id))
    # control 우세
    for v in (0.95, 0.96, 0.94, 0.95, 0.97):
        _push_metric("1.0.0", v)
    for v in (0.50, 0.51, 0.49, 0.50, 0.52):
        _push_metric("1.1.0", v)
    ab_test_service.evaluate_test("t1")

    finalized = ab_test_service.promote_winner("t1")

    assert finalized.status == "aborted"
    assert deployment_service.get_deployment(test.treatment_deployment_id).status == "stopped"
    assert deployment_service.get_deployment(primary.deployment_id).status == "running"


@pytest.mark.unit
def test_promote_before_evaluate_rejected():
    primary = _create_primary()
    ab_test_service.create_test(_ab_request(primary.deployment_id))
    with pytest.raises(HTTPException) as exc:
        ab_test_service.promote_winner("t1")
    assert exc.value.status_code == 409
