"""배포 서비스/전략 단위 테스트 (Docker는 mock)"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from docker.errors import ImageNotFound
from fastapi import HTTPException

from config.server_manager import save_servers
from models.packaging_schemas import DeploymentRequest, ModelRegisterRequest
from services import deployment_service, model_registry


@pytest.fixture()
def setup_world(tmp_path):
    """모델 + 노드 설정 셋업"""
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
            "main": {
                "base_url": "unix://var/run/docker.sock",
                "label": "central",
                "type": "local",
                "role": "central",
            },
            "silo-2": {
                "base_url": "tcp://localhost:2372",
                "label": "silo-2",
                "type": "remote",
                "role": "client",
                "tls": False,
            },
        }
    )


def _fake_docker_client() -> MagicMock:
    client = MagicMock()
    container = MagicMock()
    container.id = "container-id-abc"
    container.short_id = "abc"
    client.containers.create.return_value = container
    client.images.get.return_value = MagicMock()  # 이미지 존재
    return client


@pytest.mark.unit
def test_realtime_deployment_creates_and_starts_container(setup_world):
    fake = _fake_docker_client()
    request = DeploymentRequest(
        model_name="alpha",
        version="1.0.0",
        strategy="realtime",
        target_node_ids=["silo-2"],
    )

    with patch("services.deployment_service.get_docker_client", return_value=fake):
        entry = deployment_service.create_deployment(request)

    assert entry.status == "running"
    assert entry.container_map == {"silo-2": "container-id-abc"}
    assert entry.image_tag == "fed-model-alpha:1.0.0"
    # restart policy=always, autostart=True
    create_kwargs = fake.containers.create.call_args.kwargs
    assert create_kwargs["restart_policy"] == {"Name": "always"}
    fake.containers.create.return_value.start.assert_called_once()


@pytest.mark.unit
def test_batch_deployment_does_not_autostart(setup_world):
    fake = _fake_docker_client()
    request = DeploymentRequest(
        model_name="alpha",
        version="1.0.0",
        strategy="batch",
        target_node_ids=["silo-2"],
    )

    with patch("services.deployment_service.get_docker_client", return_value=fake):
        entry = deployment_service.create_deployment(request)

    assert entry.status == "running"
    fake.containers.create.return_value.start.assert_not_called()
    labels = fake.containers.create.call_args.kwargs["labels"]
    assert labels["fed.batch"] == "pending"


@pytest.mark.unit
def test_edge_strategy_rejects_central_role(setup_world):
    fake = _fake_docker_client()
    request = DeploymentRequest(
        model_name="alpha",
        version="1.0.0",
        strategy="edge",
        target_node_ids=["main"],  # central role
    )

    with patch("services.deployment_service.get_docker_client", return_value=fake):
        with pytest.raises(HTTPException) as exc:
            deployment_service.create_deployment(request)
    assert exc.value.status_code == 400
    # 실패한 배포 기록도 남아 있어야 함
    deployments = deployment_service.list_deployments()
    assert any(d.status == "failed" for d in deployments)


@pytest.mark.unit
def test_unknown_node_rejected_before_creation(setup_world):
    request = DeploymentRequest(
        model_name="alpha",
        version="1.0.0",
        strategy="realtime",
        target_node_ids=["does-not-exist"],
    )

    with pytest.raises(HTTPException) as exc:
        deployment_service.create_deployment(request)
    assert exc.value.status_code == 404


@pytest.mark.unit
def test_unknown_model_rejected(setup_world):
    request = DeploymentRequest(
        model_name="missing",
        version="9.9.9",
        strategy="realtime",
        target_node_ids=["silo-2"],
    )

    with pytest.raises(HTTPException) as exc:
        deployment_service.create_deployment(request)
    assert exc.value.status_code == 404


@pytest.mark.unit
def test_rollback_to_previous_deployment(setup_world):
    fake = _fake_docker_client()
    with patch("services.deployment_service.get_docker_client", return_value=fake):
        first = deployment_service.create_deployment(
            DeploymentRequest(
                model_name="alpha",
                version="1.0.0",
                strategy="realtime",
                target_node_ids=["silo-2"],
            )
        )
        # 두 번째 배포 (현재)
        second_fake = _fake_docker_client()
        with patch("services.deployment_service.get_docker_client", return_value=second_fake):
            second = deployment_service.create_deployment(
                DeploymentRequest(
                    model_name="alpha",
                    version="1.0.0",
                    strategy="realtime",
                    target_node_ids=["silo-2"],
                )
            )

        # 두 번째 → 첫 번째로 롤백
        rollback_fake = _fake_docker_client()
        with patch("services.deployment_service.get_docker_client", return_value=rollback_fake):
            new_entry = deployment_service.rollback_deployment(second.deployment_id)

    assert second.previous_deployment_id == first.deployment_id
    assert new_entry.status == "running"
    assert new_entry.deployment_id not in {first.deployment_id, second.deployment_id}

    after = deployment_service.get_deployment(second.deployment_id)
    assert after.status == "rolled_back"


@pytest.mark.unit
def test_image_pulled_when_missing_locally(setup_world):
    fake = MagicMock()
    fake.images.get.side_effect = ImageNotFound("missing")
    fake.images.pull.return_value = MagicMock()
    container = MagicMock()
    container.id = "cid"
    fake.containers.create.return_value = container

    request = DeploymentRequest(
        model_name="alpha",
        version="1.0.0",
        strategy="realtime",
        target_node_ids=["silo-2"],
    )

    with patch("services.deployment_service.get_docker_client", return_value=fake):
        entry = deployment_service.create_deployment(request)

    fake.images.pull.assert_called_once_with("fed-model-alpha:1.0.0")
    assert entry.status == "running"
