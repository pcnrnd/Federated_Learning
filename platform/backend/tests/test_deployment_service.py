"""배포 서비스/전략 단위 테스트 (Docker는 mock)"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from docker.errors import ImageNotFound, NotFound
from fastapi import HTTPException

from config.server_manager import save_servers
from models.packaging_schemas import DeploymentRequest, DeploymentTargetResult, ModelRegisterRequest
from services import deployment_runtime, deployment_service, model_registry


@pytest.fixture()
def setup_world(tmp_path, monkeypatch):
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
    # 이 파일은 전략 단위 시험이다. 실제 image transfer/HTTP 확인은 test_deployment_runtime에서 검증.
    monkeypatch.setattr(deployment_runtime, "pinned_package", lambda *_args: ("sha256:fixture", {}))
    monkeypatch.setattr(deployment_runtime, "probe_inputs", lambda *_args: [[1]])
    monkeypatch.setattr(deployment_runtime, "ensure_image", lambda *_args: None)
    monkeypatch.setattr(deployment_runtime, "verify_target", lambda _c, container, *_args, **_kw:
        DeploymentTargetResult(status="running", container_id=container.id, image_id="sha256:fixture",
            verified_at=deployment_service._now_iso()))


def _fake_docker_client() -> MagicMock:
    client = MagicMock()
    container = MagicMock()
    container.id = "container-id-abc"
    container.short_id = "abc"
    client.containers.create.return_value = container
    def get(identity):
        if identity == container.id:
            return container
        raise NotFound("fixture name absent")
    client.containers.get.side_effect = get
    client.containers.list.return_value = []
    container.status = "created"
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
    assert entry.image_tag == "sha256:fixture"
    # restart policy=always, autostart=True
    create_kwargs = fake.containers.create.call_args.kwargs
    assert create_kwargs["restart_policy"] == {"Name": "always"}
    fake.containers.create.return_value.start.assert_called_once()


@pytest.mark.unit
def test_batch_deployment_reserves_schedule_without_creating_before_due(setup_world):
    fake = _fake_docker_client()
    request = DeploymentRequest(
        model_name="alpha",
        version="1.0.0",
        strategy="batch",
        target_node_ids=["silo-2"],
    )

    with patch("services.deployment_service.get_docker_client", return_value=fake):
        entry = deployment_service.create_deployment(request)

    assert entry.status == "pending" and entry.is_schedule and entry.schedule_active
    assert entry.next_due_at and entry.interval_seconds == 60
    fake.containers.create.assert_not_called()


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
        result = deployment_service.create_deployment(request)
    assert result.status == "failed" and result.target_results["main"].error_code == "HTTPException"
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
    fake = _fake_docker_client()
    fake.images.get.side_effect = ImageNotFound("missing")
    fake.images.pull.return_value = MagicMock()
    request = DeploymentRequest(
        model_name="alpha",
        version="1.0.0",
        strategy="realtime",
        target_node_ids=["silo-2"],
    )

    with patch("services.deployment_service.get_docker_client", return_value=fake):
        entry = deployment_service.create_deployment(request)

    fake.images.pull.assert_called_once_with("sha256:fixture")
    assert entry.status == "running"
