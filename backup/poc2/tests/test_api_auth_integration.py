"""FED_API_KEY 통합 테스트 — TestClient + X-FED-API-Key 헤더 (curl 스타일)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from main import app

    return TestClient(app)


@pytest.fixture()
def api_key_client(monkeypatch):
    """FED_API_KEY=secret-test-key 로 보호된 API 클라이언트."""
    import config.settings as settings

    monkeypatch.setattr(settings, "API_KEY", "secret-test-key")
    from main import app

    return TestClient(app)


@pytest.mark.unit
def test_api_without_key_when_unconfigured(client):
    """API Key 미설정 시 /api/* 는 인증 없이 접근 가능."""
    resp = client.get("/api/models")
    assert resp.status_code == 200


@pytest.mark.unit
def test_api_rejects_missing_key_when_configured(api_key_client):
    """FED_API_KEY 설정 시 헤더 없으면 401."""
    resp = api_key_client.get("/api/models")
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == "unauthorized"
    assert "API Key" in body["detail"]


@pytest.mark.unit
def test_api_rejects_wrong_key_when_configured(api_key_client):
    """잘못된 키는 401."""
    resp = api_key_client.get(
        "/api/models",
        headers={"X-FED-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401


@pytest.mark.unit
def test_api_accepts_valid_key_when_configured(api_key_client):
    """올바른 X-FED-API-Key 로 /api/* 접근."""
    resp = api_key_client.get(
        "/api/models",
        headers={"X-FED-API-Key": "secret-test-key"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.unit
def test_dashboard_and_probes_skip_api_key(api_key_client):
    """대시보드 UI·probe는 API Key 없이 접근 가능."""
    for path in ("/dashboard", "/healthz", "/readyz", "/"):
        resp = api_key_client.get(path)
        assert resp.status_code in (200, 503), f"{path} should not require API key"


@pytest.mark.unit
def test_post_with_api_key_and_idempotency(api_key_client, tmp_path):
    """POST + API Key + 멱등성 헤더 조합."""
    weights = tmp_path / "auth-model.pt"
    weights.write_bytes(b"weights")
    headers = {
        "X-FED-API-Key": "secret-test-key",
        "X-Idempotency-Key": "auth-idem-1",
    }
    payload = {
        "name": "auth-model",
        "version": "1.0.0",
        "framework": "pytorch",
        "weights_path": str(weights),
    }
    first = api_key_client.post("/api/models", json=payload, headers=headers)
    second = api_key_client.post("/api/models", json=payload, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["created_at"] == second.json()["created_at"]
