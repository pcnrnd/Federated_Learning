"""Phase 2 API 완성도 — 에러 스키마, 멱등성, pagination, reconcile 테스트"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models.monitoring_schemas import MetricIngest
from models.packaging_schemas import DeploymentRequest, ModelRegisterRequest
from models.federated_schemas import SiloGroupRequest
from models.resource_schemas import ResourceLimit, ResourceSample
from services import deployment_service, metric_store, model_registry, resource_service


@pytest.fixture()
def client():
    from main import app

    return TestClient(app)


@pytest.fixture()
def seeded_model(tmp_path):
    weights = tmp_path / "m.pt"
    weights.write_bytes(b"")
    return model_registry.register_model(
        ModelRegisterRequest(
            name="alpha",
            version="1.0.0",
            framework="pytorch",
            weights_path=str(weights),
        )
    )


@pytest.mark.unit
def test_error_response_shape_on_404(client):
    resp = client.get("/api/models/missing/9.9.9")
    assert resp.status_code == 404
    body = resp.json()
    assert "detail" in body
    assert body.get("code") == "http_404"


@pytest.mark.unit
def test_validation_error_has_consistent_schema(client):
    resp = client.post(
        "/api/models",
        json={"name": "x", "version": "bad", "framework": "pytorch", "weights_path": "/x"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "validation_error"
    assert "detail" in body


@pytest.mark.unit
def test_metrics_pagination_and_time_filter(client):
    for i in range(5):
        metric_store.ingest(
            MetricIngest(
                node_id="silo-1",
                model_name="alpha",
                version="1.0.0",
                metric="accuracy",
                value=0.5 + i * 0.01,
                timestamp=f"2026-05-14T00:00:0{i}Z",
            )
        )

    resp = client.get(
        "/api/monitoring/metrics",
        params={
            "model_name": "alpha",
            "version": "1.0.0",
            "start_time": "2026-05-14T00:00:02Z",
            "offset": 0,
            "limit": 2,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["offset"] == 0
    assert body["limit"] == 2


@pytest.mark.unit
def test_idempotency_key_returns_same_model(client, seeded_model, tmp_path):
    weights = tmp_path / "m2.pt"
    weights.write_bytes(b"")
    payload = {
        "name": "beta",
        "version": "1.0.0",
        "framework": "pytorch",
        "weights_path": str(weights),
    }
    headers = {"X-Idempotency-Key": "idem-model-1"}

    first = client.post("/api/models", json=payload, headers=headers)
    second = client.post("/api/models", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["name"] == second.json()["name"]
    assert first.json()["created_at"] == second.json()["created_at"]


@pytest.mark.unit
def test_idempotency_key_conflict_on_different_body(client, tmp_path):
    weights = tmp_path / "m3.pt"
    weights.write_bytes(b"")
    headers = {"X-Idempotency-Key": "idem-conflict"}
    base = {
        "framework": "pytorch",
        "weights_path": str(weights),
    }

    r1 = client.post(
        "/api/models",
        json={"name": "gamma", "version": "1.0.0", **base},
        headers=headers,
    )
    r2 = client.post(
        "/api/models",
        json={"name": "delta", "version": "1.0.0", **base},
        headers=headers,
    )

    assert r1.status_code == 201
    assert r2.status_code == 409
    assert r2.json()["code"] == "http_409"


@pytest.mark.unit
def test_deployment_reconcile_updates_stale_running_status(tmp_path):
    from config.server_manager import save_servers

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
    container.id = "cid-reconcile"
    container.status = "exited"
    fake.containers.create.return_value = container
    fake.images.get.return_value = MagicMock()
    fake.containers.get.return_value = container

    with patch("services.deployment_service.get_docker_client", return_value=fake):
        entry = deployment_service.create_deployment(
            DeploymentRequest(
                model_name="alpha",
                version="1.0.0",
                strategy="realtime",
                target_node_ids=["silo-2"],
            )
        )
        assert entry.status == "running"
        result = deployment_service.reconcile_deployment(entry.deployment_id)

    assert result.reconciled is True
    assert result.previous_status == "running"
    assert result.current_status == "stopped"
    assert "stopped" in " ".join(result.changes)


@pytest.mark.unit
def test_resource_alerts_pagination(client):
    resource_service.set_limit(ResourceLimit(silo_id="silo-1", cpu_pct_max=50.0))
    for i in range(3):
        resource_service.ingest_sample(
            ResourceSample(
                silo_id="silo-1",
                cpu_pct=80.0 + i,
                mem_pct=10.0,
                timestamp=f"2026-05-14T00:00:0{i}Z",
            )
        )

    resp = client.get("/api/resources/alerts", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 2
    assert len(body["items"]) == 2


@pytest.mark.unit
def test_silo_group_idempotency(client):
    from config.server_manager import save_servers

    save_servers(
        {
            "silo-1": {
                "base_url": "tcp://localhost:2371",
                "label": "silo-1",
                "type": "remote",
                "role": "client",
                "tls": False,
            }
        }
    )
    payload = {"group_id": "g-idem", "member_node_ids": ["silo-1"]}
    headers = {"X-Idempotency-Key": "grp-1"}

    a = client.post("/api/silo-groups", json=payload, headers=headers)
    b = client.post("/api/silo-groups", json=payload, headers=headers)

    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["group_id"] == b.json()["group_id"]


@pytest.mark.unit
def test_models_list_returns_model_entry_shape(client, seeded_model):
    resp = client.get("/api/models")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    assert "name" in items[0]
    assert "framework" in items[0]
    assert "created_at" in items[0]
