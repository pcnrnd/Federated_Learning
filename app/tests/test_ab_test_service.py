"""A·B 테스트 서비스 단위 테스트"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from config.server_manager import save_servers
from models.maintenance_schemas import ABTestRequest
from models.monitoring_schemas import MetricIngest
from models.packaging_schemas import DeploymentRequest, ModelRegisterRequest
from services import (
    ab_test_service,
    deployment_service,
    metric_store,
    model_registry,
)


@pytest.fixture(autouse=True)
def _seed(tmp_path):
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
    weights = tmp_path / "m.pt"
    weights.write_bytes(b"")
    for v in ("1.0.0", "1.1.0"):
        model_registry.register_model(
            ModelRegisterRequest(
                name="alpha",
                version=v,
                framework="pytorch",
                weights_path=str(weights),
            )
        )


def _docker_mock() -> MagicMock:
    client = MagicMock()
    container = MagicMock()
    container.id = "cid"
    container.short_id = "abc"
    client.containers.create.return_value = container
    client.containers.get.return_value = container
    client.images.get.return_value = MagicMock()
    return client


def _create_primary():
    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        return deployment_service.create_deployment(
            DeploymentRequest(
                model_name="alpha",
                version="1.0.0",
                strategy="realtime",
                target_node_ids=["silo-2"],
            )
        )


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
    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        test = ab_test_service.create_test(_ab_request(primary.deployment_id))

    assert test.status == "running"
    assert test.control_deployment_id == primary.deployment_id
    assert test.treatment_deployment_id != primary.deployment_id
    assert test.shadow_id


@pytest.mark.unit
def test_evaluate_inconclusive_when_insufficient_samples():
    primary = _create_primary()
    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        ab_test_service.create_test(_ab_request(primary.deployment_id))
    _push_metric("1.0.0", 0.9)
    _push_metric("1.1.0", 0.7)

    result = ab_test_service.evaluate_test("t1")

    assert result.winner == "inconclusive"
    assert "표본 부족" in result.message


@pytest.mark.unit
def test_evaluate_picks_treatment_when_clearly_better():
    primary = _create_primary()
    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
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
    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        ab_test_service.create_test(_ab_request(primary.deployment_id))
    for v in (0.95, 0.96, 0.94, 0.95, 0.97):
        _push_metric("1.0.0", v)
    for v in (0.50, 0.51, 0.49, 0.50, 0.52):
        _push_metric("1.1.0", v)

    result = ab_test_service.evaluate_test("t1")

    assert result.winner == "control"


@pytest.mark.unit
def test_promote_treatment_winner_promotes_shadow():
    primary = _create_primary()
    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        ab_test_service.create_test(_ab_request(primary.deployment_id))
    for v in (0.50, 0.51, 0.49, 0.50, 0.52):
        _push_metric("1.0.0", v)
    for v in (0.95, 0.96, 0.94, 0.95, 0.97):
        _push_metric("1.1.0", v)
    ab_test_service.evaluate_test("t1")

    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        finalized = ab_test_service.promote_winner("t1")

    assert finalized.status == "promoted"
    assert deployment_service.get_deployment(primary.deployment_id).status == "stopped"


@pytest.mark.unit
def test_promote_control_winner_aborts_shadow():
    primary = _create_primary()
    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        test = ab_test_service.create_test(_ab_request(primary.deployment_id))
    # control 우세
    for v in (0.95, 0.96, 0.94, 0.95, 0.97):
        _push_metric("1.0.0", v)
    for v in (0.50, 0.51, 0.49, 0.50, 0.52):
        _push_metric("1.1.0", v)
    ab_test_service.evaluate_test("t1")

    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        finalized = ab_test_service.promote_winner("t1")

    assert finalized.status == "aborted"
    assert deployment_service.get_deployment(test.treatment_deployment_id).status == "stopped"
    assert deployment_service.get_deployment(primary.deployment_id).status == "running"


@pytest.mark.unit
def test_promote_before_evaluate_rejected():
    primary = _create_primary()
    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        ab_test_service.create_test(_ab_request(primary.deployment_id))
    with pytest.raises(HTTPException) as exc:
        ab_test_service.promote_winner("t1")
    assert exc.value.status_code == 409
