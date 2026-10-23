"""G1 서버 영속·실제 측정 계약과 미지원/미수집 경계 회귀."""
from __future__ import annotations

import importlib
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from config import settings
from models.resource_schemas import ResourceLimit, ResourceSample
from services import resource_service, silo_registration_service
from silo_sdk import resources


@pytest.fixture(autouse=True)
def resource_clock(monkeypatch):
    monkeypatch.setattr(resource_service, "_now_utc", lambda: datetime(2026, 10, 19, 0, 0, 1, tzinfo=timezone.utc))


@pytest.fixture
def client(monkeypatch):
    from main import app
    monkeypatch.setattr(settings, "API_KEY", "")
    return TestClient(app)


def _register(client, silo_id="silo-1"):
    response = client.post("/api/silos", json={
        "silo_id": silo_id, "label": f"기관 {silo_id}",
        "base_url": f"tcp://{silo_id}:2375", "collect_interval_seconds": 20,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_registration_survives_service_reload_and_does_not_include_central(client):
    saved = _register(client)
    importlib.reload(silo_registration_service)
    assert client.get("/api/silos").json() == [saved]
    assert client.get("/api/silos/silo-1").json()["collect_interval_seconds"] == 20
    assert client.post("/api/silos", json=saved).status_code == 409
    assert client.delete("/api/silos/main").status_code == 409


def test_unauthorized_or_invalid_registration_does_not_create_state(client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "test-only-key")
    payload = {"silo_id": "silo-7", "label": "새 사일로", "base_url": "tcp://silo-7:2375"}
    assert client.post("/api/silos", json=payload).status_code == 401
    assert silo_registration_service.list_silos() == []
    monkeypatch.setattr(settings, "API_KEY", "")
    for invalid in ({"silo_id": "../config"}, {"collect_interval_seconds": 0},
                    {"base_url": "tcp://user:password@host:2375"}):
        assert client.post("/api/silos", json={**payload, **invalid}).status_code == 422
    assert silo_registration_service.list_silos() == []


def test_group_and_limits_reload_preserve_round_member_snapshot(client, tmp_path):
    for node in ("silo-1", "silo-2", "silo-3"):
        _register(client, node)
    group = {"group_id": "participants", "member_node_ids": ["silo-1", "silo-2"]}
    assert client.post("/api/silo-groups", json=group).status_code == 201
    weight = tmp_path / "baseline.pt"
    weight.write_bytes(b"baseline")
    assert client.post("/api/models", json={"name": "baseline", "version": "1.0.0",
        "framework": "pytorch", "weights_path": str(weight)}).status_code == 201
    request = {"model_name": "baseline", "version": "1.0.0", "group_id": "participants"}
    old_round = client.post("/api/training-rounds", json=request).json()
    changed = {**group, "member_node_ids": ["silo-1", "silo-3"]}
    assert client.put("/api/silo-groups/participants", json=changed).status_code == 200
    new_round = client.post("/api/training-rounds", json=request).json()
    assert client.get(f"/api/training-rounds/{old_round['round_id']}").json()["member_snapshot"] == ["silo-1", "silo-2"]
    assert new_round["member_snapshot"] == ["silo-1", "silo-3"]
    assert client.delete("/api/silos/silo-3").status_code == 409
    cap = {"silo_id": "silo-1", "cpu_pct_max": 75, "mem_pct_max": None}
    assert client.post("/api/resources/limits", json=cap).status_code == 201
    resource_service.clear_samples()
    assert client.get("/api/resources/limits/silo-1").json()["cpu_pct_max"] == 75
    assert resource_service.is_silo_available("silo-1") is False
    assert resource_service.gate_status("silo-1") == "unknown"
    resource_service.ingest_sample(ResourceSample(silo_id="silo-1", cpu_pct=50,
        timestamp="2026-10-19T00:00:00Z", measurement_scope={"cpu": "own cgroup"}))
    assert resource_service.is_silo_available("silo-1") is True
    assert resource_service.gate_status("silo-1") == "available"


def _cgroup(tmp_path):
    (tmp_path / "cpu.max").write_text("100000 100000")
    (tmp_path / "cpu.stat").write_text("usage_usec 10000\n")
    (tmp_path / "memory.current").write_text("256")
    (tmp_path / "memory.max").write_text("1024")
    return tmp_path


def test_cgroup_uses_own_counters_and_finite_limits(tmp_path, monkeypatch):
    root = _cgroup(tmp_path)
    ticks = iter([10.0, 11.0])
    monkeypatch.setattr(resources.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(resources.time, "sleep", lambda _: (root / "cpu.stat").write_text("usage_usec 510000\n"))
    sample = resources.sample_resources(root)
    assert (sample["cpu_cores"], sample["cpu_pct"], sample["mem_pct"]) == (0.5, 50, 25)
    assert sample["mem_used_bytes"] == 256
    assert sample["mem_limit_bytes"] == 1024
    assert sample["disk_pct"] is None and sample["capabilities"]["disk_pct"] is False


def test_unlimited_memory_keeps_actual_bytes_without_inventing_percent(tmp_path, monkeypatch):
    root = _cgroup(tmp_path)
    (root / "memory.max").write_text("max")
    ticks = iter([10.0, 11.0])
    monkeypatch.setattr(resources.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(resources.time, "sleep", lambda _: None)
    sample = resources.sample_resources(root)
    assert sample["mem_used_bytes"] == 256
    assert sample["mem_pct"] is None and sample["capabilities"]["mem_pct"] is False
    assert "mem" in sample["unavailable"]


def test_namespace_path_is_resolved_without_host_fallback(tmp_path):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    group = tmp_path / "own"
    group.mkdir()
    (group / "cpu.stat").write_text("usage_usec 10")
    (proc / "self/cgroup").write_text("0::/docker/own\n")
    (proc / "self/mountinfo").write_text(f"1 0 0:1 /docker/own {group.as_posix()} rw - cgroup2 cgroup rw\n")
    assert resources.own_cgroup(proc) == group
    (proc / "self/cgroup").write_text("0::/different\n")
    assert resources.own_cgroup(proc) is None


def test_unknown_monitored_value_blocks_but_unsupported_devices_are_not_required():
    resource_service.set_limit(ResourceLimit(silo_id="silo-1", cpu_pct_max=80))
    unknown = ResourceSample(silo_id="silo-1", timestamp="2026-10-19T00:00:00Z")
    resource_service.ingest_sample(unknown)
    assert resource_service.is_silo_available("silo-1") is False
    resource_service.set_limit(ResourceLimit(silo_id="silo-1", cpu_pct_max=80,
        disk_pct_max=90, gpu_pct_max=80))
    resource_service.ingest_sample(unknown.model_copy(update={"cpu_pct": 10,
        "measurement_scope": {"cpu": "own cgroup"},
        "capabilities": {"disk_pct": False, "gpu_pct": False}}))
    assert resource_service.is_silo_available("silo-1") is True


def test_sqlite_migration_preserves_legacy_rows_and_unavailable_metadata(monkeypatch):
    from storage.settings import get_sqlite_path
    from storage.sqlite_store import connect
    monkeypatch.setenv("FED_STORAGE", "sqlite")
    db = get_sqlite_path()
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE resource_samples (id INTEGER PRIMARY KEY AUTOINCREMENT,
            silo_id TEXT NOT NULL, cpu_pct REAL NOT NULL, mem_pct REAL NOT NULL,
            gpu_pct REAL, disk_pct REAL, timestamp TEXT NOT NULL)""")
        conn.execute("INSERT INTO resource_samples VALUES (1,'silo-1',10,20,NULL,NULL,'2026-10-19T00:00:00Z')")
    with connect(db) as conn:
        assert conn.execute("SELECT cpu_pct FROM resource_samples WHERE id=1").fetchone()[0] == 10
    sample = ResourceSample(silo_id="silo-1", cpu_pct=5, mem_used_bytes=256,
        timestamp="2026-10-19T00:00:01Z", measurement_scope={"cpu": "own cgroup"},
        unavailable={"mem": "unlimited"}, capabilities={"mem_pct": False})
    resource_service.ingest_sample(sample)
    resource_service.clear_samples()
    restored = resource_service.latest_sample("silo-1")
    assert restored.mem_pct is None and restored.mem_used_bytes == 256
    assert restored.capabilities == {"mem_pct": False}
    assert restored.measurement_scope == {"cpu": "own cgroup"}
    history, total = resource_service.list_samples("silo-1", start_time="2026-10-19T00:00:01Z")
    assert total == 1 and history[0] == sample


def test_G1_F3_legacy_raw_is_preserved_but_gate_and_resource_bar_wait_for_verified_sample(monkeypatch):
    from storage.settings import get_sqlite_path
    from storage.sqlite_store import connect
    from services import visualization_service
    monkeypatch.setenv("FED_STORAGE", "sqlite")
    db = get_sqlite_path()
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE resource_samples (id INTEGER PRIMARY KEY AUTOINCREMENT,
            silo_id TEXT NOT NULL, cpu_pct REAL NOT NULL, mem_pct REAL NOT NULL,
            gpu_pct REAL, disk_pct REAL, timestamp TEXT NOT NULL)""")
        conn.execute("INSERT INTO resource_samples VALUES (1,'silo-1',10,20,NULL,NULL,'2026-10-19T00:00:00Z')")
    resource_service.set_limit(ResourceLimit(silo_id="silo-1", cpu_pct_max=80))
    assert resource_service.latest_sample("silo-1").cpu_pct == 10
    assert resource_service.gate_status("silo-1") == "unknown"
    assert resource_service.is_silo_available("silo-1") is False
    assert visualization_service.silo_bar_resource_usage().payload["items"] == []
    with connect(db) as conn:
        row = conn.execute("SELECT cpu_pct,mem_pct,measurement_json FROM resource_samples WHERE id=1").fetchone()
        assert tuple(row) == (10, 20, "{}")
    # 새 스키마에 들어온 legacy 요청도 수용과 관측 인증을 분리한다.
    resource_service.ingest_sample(ResourceSample(silo_id="silo-1", cpu_pct=50,
        timestamp="2026-10-19T00:00:00Z"))
    assert resource_service.gate_status("silo-1") == "unknown"
    resource_service.ingest_sample(ResourceSample(silo_id="silo-1", cpu_pct=50,
        timestamp="2026-10-19T00:00:01Z", measurement_scope={"cpu": "own cgroup"}))
    assert resource_service.gate_status("silo-1") == "available"
    assert visualization_service.silo_bar_resource_usage().payload["items"] == [{"silo_id": "silo-1", "value": 50.0}]


@pytest.mark.parametrize("timestamp", ["2026-10-18T00:00:00Z", "2026-10-19T00:02:00Z", "2026-10-19T00:00:00", "not-a-time"])
def test_G1_F3_scope_without_confirmed_freshness_is_unknown_and_not_a_bar(timestamp):
    from services import visualization_service
    resource_service.set_limit(ResourceLimit(silo_id="silo-1", cpu_pct_max=80))
    resource_service.ingest_sample(ResourceSample(silo_id="silo-1", cpu_pct=10,
        timestamp=timestamp, measurement_scope={"cpu": "own cgroup"}))
    assert resource_service.gate_status("silo-1") == "unknown"
    assert visualization_service.silo_bar_resource_usage().payload["items"] == []
