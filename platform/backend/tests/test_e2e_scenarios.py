"""E2E 시나리오 — TestClient 기반, 실제 사일로/Docker 불필요.

- 학습 라운드: create → contribute → metrics → aggregate(complete)
- 모델: register → version → deploy → rollback
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from config.server_manager import save_servers
from models.monitoring_schemas import MetricIngest
from services import metric_store


@pytest.fixture()
def client():
    from main import app

    return TestClient(app)


@pytest.fixture()
def seeded_world(tmp_path):
    """사일로 2개 + 모델 + 그룹 공통 셋업."""
    save_servers(
        {
            "silo-1": {
                "base_url": "tcp://localhost:2371",
                "label": "silo-1",
                "type": "remote",
                "role": "client",
                "tls": False,
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
    weights = tmp_path / "e2e-model.pt"
    weights.write_bytes(b"e2e-weights")
    return {"weights_path": str(weights)}


def _fake_docker_client() -> MagicMock:
    client = MagicMock()
    container = MagicMock()
    container.id = "e2e-container-id"
    container.short_id = "e2e"
    client.containers.create.return_value = container
    client.images.get.return_value = MagicMock()
    return client


@pytest.mark.unit
def test_e2e_training_round_lifecycle(client, seeded_world):
    """라운드 생성 → 기여 → 메트릭 push → 집계 완료."""
    wp = seeded_world["weights_path"]

    reg = client.post(
        "/api/models",
        json={
            "name": "e2e-alpha",
            "version": "1.0.0",
            "framework": "pytorch",
            "weights_path": wp,
        },
    )
    assert reg.status_code == 201

    grp = client.post(
        "/api/silo-groups",
        json={"group_id": "e2e-g1", "member_node_ids": ["silo-1", "silo-2"]},
    )
    assert grp.status_code == 201

    rnd = client.post(
        "/api/training-rounds",
        json={
            "model_name": "e2e-alpha",
            "version": "1.0.0",
            "group_id": "e2e-g1",
            "min_contributions": 2,
        },
    )
    assert rnd.status_code == 201
    round_id = rnd.json()["round_id"]
    assert rnd.json()["status"] == "open"

    for silo, samples, params in (
        ("silo-1", 90, [10.0, 10.0]),
        ("silo-2", 10, [0.0, 0.0]),
    ):
        contrib = client.post(
            f"/api/training-rounds/{round_id}/contributions",
            json={
                "round_id": round_id,
                "silo_id": silo,
                "sample_count": samples,
                "parameters": params,
            },
        )
        assert contrib.status_code == 202

    metric_store.ingest(
        MetricIngest(
            node_id="silo-1",
            model_name="e2e-alpha",
            version="1.0.0",
            metric="accuracy",
            value=0.91,
            timestamp="2026-05-14T12:00:00Z",
        )
    )
    metrics = client.get(
        "/api/monitoring/metrics",
        params={"model_name": "e2e-alpha", "version": "1.0.0"},
    )
    assert metrics.status_code == 200
    assert metrics.json()["total"] >= 1

    agg = client.post(f"/api/training-rounds/{round_id}/aggregate")
    assert agg.status_code == 200
    assert agg.json()["contributor_count"] == 2
    assert agg.json()["parameters"][0] == pytest.approx(9.0)

    done = client.get(f"/api/training-rounds/{round_id}")
    assert done.status_code == 200
    assert done.json()["status"] == "completed"


@pytest.mark.unit
def test_e2e_model_register_version_deploy_rollback(client, seeded_world):
    """모델 등록 → 버전 추가 → 배포 → 롤백."""
    wp = seeded_world["weights_path"]

    v1 = client.post(
        "/api/models",
        json={
            "name": "e2e-deploy",
            "version": "1.0.0",
            "framework": "pytorch",
            "weights_path": wp,
        },
    )
    assert v1.status_code == 201

    wp2 = wp.replace(".pt", "-v2.pt")
    from pathlib import Path

    Path(wp2).write_bytes(b"v2")
    v2 = client.post(
        "/api/models",
        json={
            "name": "e2e-deploy",
            "version": "1.1.0",
            "framework": "pytorch",
            "weights_path": wp2,
        },
    )
    assert v2.status_code == 201

    versions = client.get("/api/models/e2e-deploy/versions")
    assert versions.status_code == 200
    assert len(versions.json()) == 2

    fake = _fake_docker_client()
    with patch("services.deployment_service.get_docker_client", return_value=fake):
        dep1 = client.post(
            "/api/deployments",
            json={
                "model_name": "e2e-deploy",
                "version": "1.0.0",
                "strategy": "realtime",
                "target_node_ids": ["silo-1"],
            },
        )
        assert dep1.status_code == 201
        dep1_id = dep1.json()["deployment_id"]

        dep2_fake = _fake_docker_client()
        with patch("services.deployment_service.get_docker_client", return_value=dep2_fake):
            dep2 = client.post(
                "/api/deployments",
                json={
                    "model_name": "e2e-deploy",
                    "version": "1.1.0",
                    "strategy": "realtime",
                    "target_node_ids": ["silo-1"],
                },
            )
        assert dep2.status_code == 201
        dep2_id = dep2.json()["deployment_id"]

        rollback_fake = _fake_docker_client()
        with patch("services.deployment_service.get_docker_client", return_value=rollback_fake):
            rb = client.post(f"/api/deployments/{dep2_id}/rollback")

    assert rb.status_code == 200
    assert rb.json()["status"] == "running"
    assert rb.json()["deployment_id"] != dep2_id

    rolled = client.get(f"/api/deployments/{dep2_id}")
    assert rolled.status_code == 200
    assert rolled.json()["status"] == "rolled_back"
    assert rolled.json()["previous_deployment_id"] == dep1_id
