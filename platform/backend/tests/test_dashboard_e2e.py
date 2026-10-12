"""대시보드 UI 스모크 — TestClient + HTML 구조 검증 (Playwright 미설치 환경 대체).

반응형 메타·빈 상태·401 배너·로딩 마커 등 핵심 DOM 요소가
템플릿/정적 자산에 존재하는지 확인한다.

/dashboard 는 static/dist/index.html 이 있으면 React SPA 를, 없으면 Jinja
dashboard.html 을 반환한다. Jinja DOM 단언은 배포 형상에 좌우되지 않도록
`fallback_client` 픽스처로 폴백 경로를 강제한 뒤 수행한다.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from main import app

    return TestClient(app)


@pytest.fixture()
def fallback_client(tmp_path, monkeypatch):
    """SPA 빌드본이 없는 폴백 형상 — _BASE_DIR 을 비운 임시 경로로 돌려 Jinja 템플릿을 강제한다."""
    import main

    monkeypatch.setattr(main, "_BASE_DIR", tmp_path)
    return TestClient(main.app)


@pytest.mark.unit
def test_dashboard_page_returns_html_with_responsive_viewport(client):
    """대시보드 HTML이 200이며 viewport 메타가 포함된다."""
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    html = resp.text
    assert 'name="viewport"' in html
    assert 'content="width=device-width' in html


@pytest.mark.unit
def test_dashboard_has_chart_canvas_and_empty_state_markers(fallback_client):
    """5종 차트 canvas/div와 empty-state 문구 placeholder가 존재한다."""
    html = fallback_client.get("/dashboard").text
    for element_id in (
        "chart-timeseries",
        "chart-histogram",
        "chart-bar",
        "chart-heatmap",
        "chart-topology",
    ):
        assert f'id="{element_id}"' in html
    for empty_id in (
        "empty-timeseries",
        "empty-histogram",
        "empty-bar",
        "empty-heatmap",
        "empty-topology",
    ):
        assert f'id="{empty_id}"' in html
        assert "hidden" in html.split(f'id="{empty_id}"')[1][:80]


@pytest.mark.unit
def test_dashboard_has_auth_banner_and_api_key_input(fallback_client):
    """401 재시도 UI와 API Key 입력 필드가 템플릿에 포함된다."""
    html = fallback_client.get("/dashboard").text
    assert 'id="auth-banner"' in html
    assert 'id="auth-retry-btn"' in html
    assert 'id="api-key-input"' in html
    assert "FED_API_KEY" in html


@pytest.mark.unit
def test_dashboard_static_assets_linked(fallback_client):
    """CSS/JS 정적 자산이 링크되어 있다."""
    html = fallback_client.get("/dashboard").text
    assert "/static/dashboard.css" in html
    assert "/static/dashboard.js" in html


@pytest.mark.unit
def test_dashboard_ops_panel_structure(fallback_client):
    """운영 현황 read-only 패널 DOM 구조."""
    html = fallback_client.get("/dashboard").text
    for ops_id in ("ops-models", "ops-groups", "ops-deployments", "ops-alerts"):
        assert f'id="{ops_id}"' in html
    assert 'data-state="idle"' in html


@pytest.mark.unit
def test_dashboard_serves_spa_index_when_build_exists(tmp_path, monkeypatch):
    """SPA 빌드본이 있으면 Jinja 폴백 대신 static/dist/index.html 을 그대로 반환한다."""
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
    assert "<title>SPA</title>" in resp.text


@pytest.mark.unit
def test_dashboard_css_has_responsive_grid_rules():
    """dashboard.css에 모바일 breakpoint 규칙이 정의되어 있다."""
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "static" / "dashboard.css").read_text(
        encoding="utf-8"
    )
    assert "@media" in css
    assert re.search(r"max-width:\s*\d+px", css)


@pytest.mark.unit
def test_dashboard_js_has_error_and_empty_handlers():
    """dashboard.js에 empty/error/401 재시도 로직이 존재한다."""
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "static" / "dashboard.js").read_text(
        encoding="utf-8"
    )
    assert "unwrapPaginated" in js
    assert "auth-banner" in js or "authBanner" in js
    assert "empty-" in js or "showEmpty" in js


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
