"""Runtime probe and storage hardening tests."""
from __future__ import annotations

import pytest
from fastapi import Response

from config.yaml_store import load_yaml, save_yaml_atomic


def test_health_probe():
    from main import healthz

    assert healthz() == {"status": "ok"}


def test_api_key_auth_helper(monkeypatch):
    import config.settings as settings
    from main import _api_key_is_valid, _requires_api_key

    monkeypatch.setattr(settings, "API_KEY", "")
    assert _requires_api_key("/api/models") is False
    assert _api_key_is_valid("/api/models", None) is True

    monkeypatch.setattr(settings, "API_KEY", "secret")
    assert _requires_api_key("/api/models") is True
    assert _api_key_is_valid("/api/models", None) is False
    assert _api_key_is_valid("/api/models", "wrong") is False
    assert _api_key_is_valid("/api/models", "secret") is True
    assert _api_key_is_valid("/dashboard", None) is True


@pytest.mark.asyncio
async def test_ready_probe_reports_scheduler_state():
    from main import readyz
    from services.round_scheduler import get_scheduler

    scheduler = get_scheduler()
    await scheduler.start()
    try:
        response = Response()
        body = readyz(response)
    finally:
        await scheduler.stop()

    assert response.status_code == 200
    assert body["status"] == "ready"
    assert body["checks"]["scheduler_running"] is True
    assert body["checks"]["config_dir_exists"] is True


def test_save_yaml_atomic_roundtrip(tmp_path):
    path = tmp_path / "nested" / "data.yaml"
    save_yaml_atomic(path, {"alpha": {"version": "1.0.0"}})

    assert load_yaml(path) == {"alpha": {"version": "1.0.0"}}
    assert list(path.parent.glob("*.tmp")) == []
