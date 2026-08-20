"""알림 서비스 및 자동 롤백 트리거 테스트"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from config.server_manager import save_servers
from models.monitoring_schemas import (
    AlertRule,
    BaselineRequest,
    DistributionStats,
    MetricSample,
)
from models.packaging_schemas import DeploymentRequest, ModelRegisterRequest
from services import (
    alert_service,
    deployment_service,
    drift_detector,
    model_registry,
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
def test_auto_rollback_invokes_deployment_service(tmp_path):
    # 모델 등록 + 노드 설정
    weights = tmp_path / "m.pt"
    weights.write_bytes(b"")
    model_registry.register_model(
        ModelRegisterRequest(
            name="alpha",
            version="1.0.0",
            framework="pytorch",
            weights_path=str(weights),
        )
    )
    save_servers(
        {
            "silo-2": {
                "base_url": "tcp://localhost:2372",
                "label": "silo-2",
                "type": "remote",
                "role": "client",
                "tls": False,
            }
        }
    )

    fake = MagicMock()
    container = MagicMock()
    container.id = "cid"
    fake.containers.create.return_value = container
    fake.images.get.return_value = MagicMock()
    fake.containers.get.return_value = container

    with patch("services.deployment_service.get_docker_client", return_value=fake):
        first = deployment_service.create_deployment(
            DeploymentRequest(
                model_name="alpha",
                version="1.0.0",
                strategy="realtime",
                target_node_ids=["silo-2"],
            )
        )
        # 두 번째 배포 — previous_deployment_id 가 first 가 됨
        second = deployment_service.create_deployment(
            DeploymentRequest(
                model_name="alpha",
                version="1.0.0",
                strategy="realtime",
                target_node_ids=["silo-2"],
            )
        )
        assert second.previous_deployment_id == first.deployment_id

        # auto_rollback 규칙 등록 + 위반 메트릭 평가
        alert_service.upsert_rule(_rule_accuracy_lt(0.5, auto_rollback=True))
        triggered = alert_service.evaluate_metric(_sample(0.3))

    assert triggered[0].triggered_rollback_deployment_id is not None
    after = deployment_service.get_deployment(second.deployment_id)
    assert after.status == "rolled_back"
