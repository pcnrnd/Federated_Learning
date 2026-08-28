"""섀도우 배포 단위 테스트 (Docker SDK는 mock)"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from config.server_manager import save_servers
from models.maintenance_schemas import ShadowDeploymentRequest
from models.packaging_schemas import DeploymentRequest, ModelRegisterRequest
from services import deployment_service, model_registry, shadow_deployment_service


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


@pytest.mark.unit
def test_create_shadow_requires_running_primary():
    primary = _create_primary()
    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        deployment_service.stop_deployment(primary.deployment_id)
    with pytest.raises(HTTPException) as exc:
        with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
            shadow_deployment_service.create_shadow(
                ShadowDeploymentRequest(
                    primary_deployment_id=primary.deployment_id,
                    shadow_version="1.1.0",
                )
            )
    assert exc.value.status_code == 409


@pytest.mark.unit
def test_create_shadow_runs_second_deployment():
    primary = _create_primary()
    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        shadow = shadow_deployment_service.create_shadow(
            ShadowDeploymentRequest(
                primary_deployment_id=primary.deployment_id,
                shadow_version="1.1.0",
                traffic_mirror_pct=20.0,
            )
        )

    assert shadow.status == "active"
    assert shadow.primary_deployment_id == primary.deployment_id
    assert shadow.shadow_deployment_id != primary.deployment_id
    assert shadow.primary_version == "1.0.0"
    assert shadow.shadow_version == "1.1.0"
    assert shadow.traffic_mirror_pct == 20.0
    # 두 배포 모두 running
    assert deployment_service.get_deployment(shadow.shadow_deployment_id).status == "running"
    assert deployment_service.get_deployment(primary.deployment_id).status == "running"


@pytest.mark.unit
def test_promote_shadow_stops_primary():
    primary = _create_primary()
    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        shadow = shadow_deployment_service.create_shadow(
            ShadowDeploymentRequest(
                primary_deployment_id=primary.deployment_id,
                shadow_version="1.1.0",
            )
        )
        promoted = shadow_deployment_service.promote_shadow(shadow.shadow_id)

    assert promoted.status == "promoted"
    assert deployment_service.get_deployment(primary.deployment_id).status == "stopped"


@pytest.mark.unit
def test_abort_shadow_stops_shadow_keeps_primary():
    primary = _create_primary()
    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        shadow = shadow_deployment_service.create_shadow(
            ShadowDeploymentRequest(
                primary_deployment_id=primary.deployment_id,
                shadow_version="1.1.0",
            )
        )
        aborted = shadow_deployment_service.abort_shadow(shadow.shadow_id)

    assert aborted.status == "aborted"
    assert deployment_service.get_deployment(shadow.shadow_deployment_id).status == "stopped"
    assert deployment_service.get_deployment(primary.deployment_id).status == "running"


@pytest.mark.unit
def test_promote_after_promote_rejected():
    primary = _create_primary()
    with patch("services.deployment_service.get_docker_client", return_value=_docker_mock()):
        shadow = shadow_deployment_service.create_shadow(
            ShadowDeploymentRequest(
                primary_deployment_id=primary.deployment_id,
                shadow_version="1.1.0",
            )
        )
        shadow_deployment_service.promote_shadow(shadow.shadow_id)
        with pytest.raises(HTTPException) as exc:
            shadow_deployment_service.promote_shadow(shadow.shadow_id)
    assert exc.value.status_code == 409
