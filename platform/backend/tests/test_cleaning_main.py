"""정제 서비스 단독 진입점(cleaning_main) 테스트"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cleaning_main import app
from config.server_manager import save_servers

client = TestClient(app)


def _seed_servers() -> None:
    save_servers(
        {
            f"silo-{i}": {
                "base_url": f"tcp://localhost:237{i}",
                "label": f"silo-{i}",
                "type": "remote",
                "role": "client",
                "tls": False,
            }
            for i in (1, 2)
        }
    )


def test_standalone_exposes_only_cleaning_surface():
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/api/cleaning-recipes").status_code == 200
    assert client.get("/api/cleaning-jobs").status_code == 200
    # 통합 플랫폼 전용 라우터는 싣지 않는다
    assert client.get("/api/training-rounds").status_code == 404
    assert client.get("/api/models").status_code == 404


def test_standalone_job_lifecycle_end_to_end():
    _seed_servers()
    r = client.post(
        "/api/silo-groups",
        json={"group_id": "g1", "member_node_ids": ["silo-1", "silo-2"]},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/cleaning-recipes",
        json={
            "name": "hospital",
            "version": "1.0.0",
            "steps": [{"type": "drop_nulls", "params": {"columns": ["age"]}}],
        },
    )
    assert r.status_code == 201
    r = client.post(
        "/api/cleaning-jobs",
        json={
            "job_id": "j1",
            "recipe_name": "hospital",
            "recipe_version": "1.0.0",
            "group_id": "g1",
            "dataset_label": "patients",
        },
    )
    assert r.status_code == 201
    assert [s["silo_id"] for s in r.json()["shards"]] == ["silo-1", "silo-2"]

    for idx, silo in enumerate(["silo-1", "silo-2"]):
        start = client.post(
            f"/api/cleaning-jobs/j1/shards/{idx}/start", json={"silo_id": silo}
        )
        assert start.status_code == 200
        report = client.post(
            f"/api/cleaning-jobs/j1/shards/{idx}/report",
            json={
                "job_id": "j1",
                "shard_index": idx,
                "silo_id": silo,
                "rows_in": 100,
                "rows_out": 90,
                "step_counters": {"drop_nulls": 10},
                "started_at": "2026-09-23T00:00:00Z",
                "completed_at": "2026-09-23T00:01:00Z",
            },
        )
        assert report.status_code == 200

    job = client.get("/api/cleaning-jobs/j1").json()
    assert job["status"] == "completed"
    assert (job["total_rows_in"], job["total_rows_out"]) == (200, 180)
    assert job["aggregated_counters"] == {"drop_nulls": 20}


def test_standalone_unknown_recipe_job_rejected():
    r = client.post(
        "/api/cleaning-jobs",
        json={
            "job_id": "j2",
            "recipe_name": "nope",
            "recipe_version": "1.0.0",
            "group_id": "g1",
            "dataset_label": "x",
        },
    )
    assert r.status_code == 404


def test_standalone_api_key_gate(monkeypatch):
    import config.settings as settings

    monkeypatch.setattr(settings, "API_KEY", "secret")
    assert client.get("/api/cleaning-recipes").status_code == 401
    ok = client.get(
        "/api/cleaning-recipes", headers={settings.API_KEY_HEADER: "secret"}
    )
    assert ok.status_code == 200
    assert client.get("/healthz").status_code == 200
