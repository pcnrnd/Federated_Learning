"""대시보드 UI 스모크 — TestClient 로 /dashboard 서빙 동작을 검증한다.

/dashboard 는 static/dist/index.html(React SPA 빌드본)이 있으면 그대로 반환하고,
없으면 404 를 반환한다. 실제 빌드 여부와 무관하도록 _BASE_DIR 을 임시 경로로 돌려 검증한다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from main import app

    return TestClient(app)


@pytest.fixture()
def empty_base_client(tmp_path, monkeypatch):
    """SPA 빌드본이 없는 형상 — _BASE_DIR 을 비운 임시 경로로 돌린다."""
    import main

    monkeypatch.setattr(main, "_BASE_DIR", tmp_path)
    return TestClient(main.app)


@pytest.mark.unit
def test_dashboard_serves_spa_index_when_build_exists(tmp_path, monkeypatch):
    """SPA 빌드본이 있으면 static/dist/index.html 을 그대로 반환한다(200, viewport 메타, no-cache)."""
    import main

    dist_dir = tmp_path / "static" / "dist"
    dist_dir.mkdir(parents=True)
    dist_dir.joinpath("index.html").write_text(
        '<!doctype html><meta name="viewport" content="width=device-width"><title>SPA</title>',
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "_BASE_DIR", tmp_path)

    resp = TestClient(main.app).get("/dashboard")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert 'name="viewport"' in resp.text
    assert "<title>SPA</title>" in resp.text
    assert resp.headers.get("cache-control") == "no-cache"


@pytest.mark.unit
def test_dashboard_returns_404_when_build_missing(empty_base_client):
    """SPA 빌드본이 없으면 404 JSON 을 반환하고 캐시하지 않는다."""
    resp = empty_base_client.get("/dashboard")
    assert resp.status_code == 404
    assert resp.json()["code"] == "dashboard_unavailable"
    assert resp.headers.get("cache-control") == "no-cache"


@pytest.mark.unit
def test_composite_dashboard_api_empty_model_returns_partial_charts(client):
    """데이터 없을 때 통합 API가 null/error로 부분 응답을 반환한다."""
    resp = client.get(
        "/api/dashboard",
        params={"model_name": "nonexistent", "version": "0.0.0", "metric": "accuracy"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "timeseries" in body
    # 빈 모델 — timeseries는 error 또는 빈 payload
    ts = body["timeseries"]
    assert ts is None or isinstance(ts, dict)
