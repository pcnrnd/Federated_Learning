"""알림 서비스 및 자동 롤백 트리거 테스트"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from g5_helpers import request, setup_world
from models.monitoring_schemas import (
    AlertRule,
    BaselineRequest,
    DistributionStats,
    MetricSample,
)
from services import (
    alert_service,
    deployment_service,
    drift_detector,
)


def _rule_accuracy_lt(threshold: float = 0.5, auto_rollback: bool = False) -> AlertRule:
    return AlertRule(
        rule_id="r-accuracy",
        model_name="alpha",
        metric="accuracy",
        threshold=threshold,
        comparison="lt",
        auto_rollback=auto_rollback,
    )


def _sample(value: float) -> MetricSample:
    return MetricSample(
        node_id="silo-2",
        model_name="alpha",
        version="1.0.0",
        metric="accuracy",
        value=value,
        timestamp="2026-05-14T00:00:00Z",
    )


@pytest.mark.unit
def test_evaluate_metric_does_not_fire_when_within_threshold():
    alert_service.upsert_rule(_rule_accuracy_lt(0.5))

    triggered = alert_service.evaluate_metric(_sample(0.8))

    assert triggered == []
    alerts, total = alert_service.list_alerts()
    assert total == 0
    assert alerts == []


@pytest.mark.unit
def test_evaluate_metric_fires_when_violated():
    alert_service.upsert_rule(_rule_accuracy_lt(0.5))

    triggered = alert_service.evaluate_metric(_sample(0.3))

    assert len(triggered) == 1
    assert triggered[0].status == "open"
    assert triggered[0].observed_value == 0.3


@pytest.mark.unit
def test_ack_alert_transitions_to_acked():
    alert_service.upsert_rule(_rule_accuracy_lt(0.5))
    [opened] = alert_service.evaluate_metric(_sample(0.3))

    acked = alert_service.ack_alert(opened.alert_id)

    assert acked.status == "acked"


@pytest.mark.unit
def test_drift_critical_emits_retrain_trigger():
    drift_detector.set_baseline(
        BaselineRequest(
            model_name="alpha",
            version="1.0.0",
            feature="age",
            bin_edges=[0.0, 1.0, 2.0, 3.0, 4.0],
            bin_counts=[100, 100, 100, 100],
        )
    )
    stats = DistributionStats(
        node_id="silo-2",
        model_name="alpha",
        version="1.0.0",
        feature="age",
        bin_edges=[0.0, 1.0, 2.0, 3.0, 4.0],
        bin_counts=[10, 50, 150, 190],
        timestamp="2026-05-14T00:00:00Z",
    )
    report = drift_detector.detect_drift(stats)

    _, retrain = alert_service.evaluate_drift(report)

    assert retrain is not None
    assert retrain.model_name == "alpha"
    triggers = alert_service.latest_retrain_triggers(model_name="alpha")
    assert len(triggers) == 1


@pytest.mark.unit
def test_drift_stable_no_retrain_trigger():
    drift_detector.set_baseline(
        BaselineRequest(
            model_name="alpha",
            version="1.0.0",
            feature="age",
            bin_edges=[0.0, 1.0, 2.0],
            bin_counts=[100, 100],
        )
    )
    stats = DistributionStats(
        node_id="silo-2",
        model_name="alpha",
        version="1.0.0",
        feature="age",
        bin_edges=[0.0, 1.0, 2.0],
        bin_counts=[101, 99],
        timestamp="2026-05-14T00:00:00Z",
    )
    report = drift_detector.detect_drift(stats)

    alerts, retrain = alert_service.evaluate_drift(report)

    assert retrain is None
    assert alerts == []


@pytest.mark.unit
def test_auto_rollback_invokes_deployment_service(tmp_path, monkeypatch):
    # 검증된 패키지/HTTP/Docker 경계만 대역으로 두고 실제 배포·복원 서비스를 호출한다.
    world = setup_world(tmp_path, monkeypatch)
    deployment_request = request(target_node_ids=["silo-2"])
    first = deployment_service.create_deployment(deployment_request)
    second = deployment_service.create_deployment(deployment_request)
    assert first.status == second.status == "running"
    assert second.previous_deployment_id == first.deployment_id

    rule = _rule_accuracy_lt(0.5, auto_rollback=True).model_copy(update={"model_name": world.model.name})
    sample = _sample(0.3).model_copy(update={"model_name": world.model.name})
    alert_service.upsert_rule(rule)
    with patch.object(deployment_service, "rollback_deployment", wraps=deployment_service.rollback_deployment) as rollback:
        triggered = alert_service.evaluate_metric(sample)

    rollback.assert_called_once_with(second.deployment_id)
    assert len(triggered) == 1
    assert triggered[0].triggered_rollback_deployment_id is not None
    after = deployment_service.get_deployment(second.deployment_id)
    assert after.status == "rolled_back"
    restored = deployment_service.get_deployment(triggered[0].triggered_rollback_deployment_id)
    assert restored.deployment_id == after.rollback_run_id
    assert restored.status == "running" and restored.verified_at
    assert restored.model_name == world.model.name and restored.version == "1.0.0"
    assert restored.target_node_ids == first.target_node_ids == ["silo-2"]
    assert restored.configuration == first.configuration
    assert restored.target_results["silo-2"].status == "running"
