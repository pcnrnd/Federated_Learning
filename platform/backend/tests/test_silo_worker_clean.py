"""사일로 워커 정제(clean) — 로컬 다원천 파일에 레시피 적용 후 통계만 보고"""
from __future__ import annotations

import argparse
import json

import pytest

from scripts import silo_worker
from silo_sdk import synthetic


class _CleanClient:
    """정제 샤드 API 대역 — 보고 payload를 기록한다."""

    def __init__(self, recipe: dict) -> None:
        self.recipe = recipe
        self.started: list[tuple] = []
        self.reports: list[dict] = []

    def fetch_cleaning_recipe(self, name, version):
        return self.recipe

    def start_cleaning_shard(self, job_id, shard_index):
        self.started.append((job_id, shard_index))
        return {}

    def report_cleaning_shard(self, job_id, shard_index, rows_in, rows_out, step_counters,
                              **kwargs):
        self.reports.append({"job_id": job_id, "shard_index": shard_index, "rows_in": rows_in,
                             "rows_out": rows_out, "step_counters": step_counters, **kwargs})
        return {"status": "failed" if kwargs.get("error") else "completed"}


def _args(tmp_path, **extra) -> argparse.Namespace:
    base = dict(central="http://c", silo_id="silo-1", job_id="j1", shard_index=0,
                recipe_name="r", recipe_version="1.0.0", data_dir=str(tmp_path))
    return argparse.Namespace(**{**base, **extra})


def _install(monkeypatch, client: _CleanClient) -> None:
    monkeypatch.setattr(silo_worker, "SiloClient", lambda *_a, **_k: client)


@pytest.mark.unit
def test_clean_with_mapping_uses_local_source_files(tmp_path, monkeypatch, capsys):
    recipe = {
        "steps": [
            {"type": "map_schema", "params": {"sources": ["period_a"]}},
            {"type": "validate_schema", "params": {"source": "period_a"}},
        ],
        "mapping": {**synthetic.HVC_MAPPING, "common_schema": {
            k: v for k, v in synthetic.HVC_MAPPING["common_schema"].items()
            if k in ("id", "x1", "y")}},
    }
    client = _CleanClient(recipe)
    _install(monkeypatch, client)

    silo_worker.run_clean(_args(tmp_path))

    tables = {name: len(rows) for name, rows in silo_worker.load_local_sources(
        "silo-1", str(tmp_path)).items()}
    report = client.reports[0]
    assert (tmp_path / "period_a.csv").is_file()  # 로컬 파일을 만들어 읽었다
    assert report["rows_in"] == sum(tables.values())
    counters = report["step_counters"]
    assert report["rows_out"] == counters["validate_schema.out"]
    assert counters["map_schema.rows.period_a"] == tables["period_a"]
    assert counters["validate_schema.excluded.missing"] > 0
    assert counters["validate_schema.excluded.out_of_range"] > 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["rows_out"] == report["rows_out"]


@pytest.mark.unit
def test_clean_without_mapping_keeps_legacy_dummy_rows(tmp_path, monkeypatch):
    recipe = {"steps": [{"type": "dedupe", "params": {"keys": ["id"]}}]}
    client = _CleanClient(recipe)
    _install(monkeypatch, client)

    silo_worker.run_clean(_args(tmp_path))

    report = client.reports[0]
    assert report["rows_in"] == len(silo_worker._dirty_rows("silo-1"))
    assert report["step_counters"] == {"dedupe": 10}
    assert not (tmp_path / "period_a.csv").exists()


@pytest.mark.unit
def test_clean_reports_schema_fingerprint(tmp_path, monkeypatch):
    from silo_sdk.integration import schema_fingerprint

    recipe = {
        "steps": [
            {"type": "map_schema", "params": {"sources": ["period_a", "period_b"]}},
            {"type": "union_sources",
             "params": {"sources": ["period_a", "period_b"], "into": "periods"}},
            {"type": "validate_schema", "params": {}},
        ],
        "mapping": {**synthetic.HVC_MAPPING, "common_schema": {
            k: v for k, v in synthetic.HVC_MAPPING["common_schema"].items()
            if k in ("id", "x1", "y")}},
    }
    client = _CleanClient(recipe)
    _install(monkeypatch, client)

    silo_worker.run_clean(_args(tmp_path))

    report = client.reports[0]
    assert report["schema_fingerprint"] == schema_fingerprint(
        [{"id": "E", "x1": 0.0, "y": 0.0}])
    assert report["step_counters"]["union_sources.duplicates.cross"] > 0
    assert report["step_counters"]["union_sources.duplicates.within"] > 0


# ---------- 사일로 간 수직 정렬 (align, F4) ----------

ALIGN_RECIPE = {
    "steps": [
        {"type": "map_schema", "params": {"sources": ["period_a", "period_b", "entity"]}},
        {"type": "union_sources",
         "params": {"sources": ["period_a", "period_b"], "into": "periods"}},
        {"type": "join_sources", "params": {"left": "periods", "right": "entity", "into": "base"}},
        {"type": "validate_schema", "params": {}},
    ],
    "mapping": {**synthetic.HVC_MAPPING, "common_schema": {
        k: v for k, v in synthetic.HVC_MAPPING["common_schema"].items() if k != "x2"}},
}


class _AlignClient(_CleanClient):
    def __init__(self) -> None:
        super().__init__(ALIGN_RECIPE)
        self.submitted: list[str] = []
        self.polls = 0
        self.align_report: dict = {}

    def submit_alignment_keys(self, alignment_id, hashed_keys):
        self.submitted = list(hashed_keys)
        return {}

    def get_alignment_intersection(self, alignment_id):
        from silo_sdk.client import SiloClientError

        self.polls += 1
        if self.polls == 1:
            raise SiloClientError(409, "다른 사일로 대기")
        return {"status": "ready", "hashed_keys": sorted(self.submitted)[:5]}

    def report_alignment(self, alignment_id, matched, excluded, order_digest):
        self.align_report = {"matched": matched, "excluded": excluded,
                             "order_digest": order_digest}
        return {}


def _align_args(tmp_path) -> argparse.Namespace:
    return argparse.Namespace(central="http://c", silo_id="silo-4", alignment_id="a1",
                              recipe_name="r", recipe_version="1.0.0", data_dir=str(tmp_path),
                              wait=5.0, poll_interval=0.0)


@pytest.mark.unit
def test_align_sends_only_hmac_digests_and_keeps_intersection(tmp_path, monkeypatch, capsys):
    import csv
    import re

    monkeypatch.setenv("FED_ALIGN_KEY", "silo-shared-align-key-for-tests")
    client = _AlignClient()
    _install(monkeypatch, client)

    silo_worker.run_align(_align_args(tmp_path))

    assert client.submitted and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in client.submitted)
    raw_ids = {r["eid"] for r in silo_worker.load_local_sources("silo-4", str(tmp_path))["entity"]}
    assert not raw_ids & set(client.submitted)
    assert client.align_report["matched"] == 5
    assert client.align_report["excluded"] == len(client.submitted) - 5
    with (tmp_path / "aligned-a1.csv").open(encoding="utf-8", newline="") as f:
        aligned = list(csv.DictReader(f))
    assert len(aligned) == 5  # 교집합 엔터티만, 서버가 준 순서대로 로컬에 남긴다
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["intersection"] == 5 and out["order_digest"] == client.align_report["order_digest"]


@pytest.mark.unit
def test_align_requires_silo_key_before_any_request(tmp_path, monkeypatch):
    monkeypatch.delenv("FED_ALIGN_KEY", raising=False)
    client = _AlignClient()
    _install(monkeypatch, client)

    with pytest.raises(SystemExit, match="FED_ALIGN_KEY"):
        silo_worker.run_align(_align_args(tmp_path))
    assert client.submitted == []


# ---------- 작업 번호 없이 배정 샤드 처리 (F7) ----------


class _AutoClient(_CleanClient):
    def __init__(self, shards: list[dict]) -> None:
        super().__init__({"steps": [{"type": "dedupe", "params": {"keys": ["id"]}}]})
        self.shards = shards
        self.fetched: list[tuple] = []

    def list_assigned_shards(self, status="pending"):
        assert status == "pending"
        return self.shards

    def fetch_cleaning_recipe(self, name, version):
        self.fetched.append((name, version))
        return self.recipe


@pytest.mark.unit
def test_clean_without_job_id_processes_assigned_pending_shards(tmp_path, monkeypatch, capsys):
    shards = [{"job_id": "c1", "shard_index": 0, "recipe_name": "r", "recipe_version": "1.0.0"},
              {"job_id": "c2", "shard_index": 3, "recipe_name": "r", "recipe_version": "2.0.0"}]
    client = _AutoClient(shards)
    _install(monkeypatch, client)

    silo_worker.run_clean(_args(tmp_path, job_id=None, shard_index=None, recipe_name=None,
                                recipe_version=None))

    assert client.started == [("c1", 0), ("c2", 3)]
    assert [(r["job_id"], r["shard_index"]) for r in client.reports] == [("c1", 0), ("c2", 3)]
    assert client.fetched == [("r", "1.0.0"), ("r", "2.0.0")]
    lines = [json.loads(x) for x in capsys.readouterr().out.strip().splitlines()]
    assert [x["job_id"] for x in lines] == ["c1", "c2"]


@pytest.mark.unit
def test_clean_without_job_id_and_no_shards_exits_quietly(tmp_path, monkeypatch, capsys):
    client = _AutoClient([])
    _install(monkeypatch, client)

    silo_worker.run_clean(_args(tmp_path, job_id=None, shard_index=None, recipe_name=None,
                                recipe_version=None))

    assert client.reports == []
    assert json.loads(capsys.readouterr().out)["event"] == "no_assigned_shards"


@pytest.mark.unit
def test_clean_with_partial_job_arguments_is_rejected(tmp_path, monkeypatch):
    _install(monkeypatch, _AutoClient([]))
    with pytest.raises(SystemExit, match="함께"):
        silo_worker.run_clean(_args(tmp_path, shard_index=None))


# ---------- 정제 실패 보고 (F8) ----------


@pytest.mark.unit
def test_clean_failure_is_reported_instead_of_leaving_shard_running(tmp_path, monkeypatch):
    recipe = {"steps": synthetic.HVC_STEPS, "mapping": synthetic.HVC_MAPPING}
    client = _CleanClient(recipe)
    _install(monkeypatch, client)
    (tmp_path / "records.json").parent.mkdir(exist_ok=True)
    synthetic.write_sources("silo-1", tmp_path)
    (tmp_path / "records.json").write_text("[]", encoding="utf-8")  # 교차 원천이 비면 정제 실패

    with pytest.raises(SystemExit, match="1건"):
        silo_worker.run_clean(_args(tmp_path))

    assert client.started == [("j1", 0)]
    report = client.reports[0]
    assert report["rows_in"] == report["rows_out"] == 0
    assert "CleaningError" in report["error"] and "공통 스키마" in report["error"]


@pytest.mark.unit
def test_clean_failure_in_one_assigned_shard_still_processes_the_rest(tmp_path, monkeypatch):
    shards = [{"job_id": "bad", "shard_index": 0, "recipe_name": "r", "recipe_version": "1"},
              {"job_id": "ok", "shard_index": 1, "recipe_name": "r", "recipe_version": "1"}]
    client = _AutoClient(shards)
    _install(monkeypatch, client)
    real = silo_worker.clean_local
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyError("columns")
        return real(*a, **k)

    monkeypatch.setattr(silo_worker, "clean_local", flaky)

    with pytest.raises(SystemExit):
        silo_worker.run_clean(_args(tmp_path, job_id=None, shard_index=None, recipe_name=None,
                                    recipe_version=None))

    assert [(r["job_id"], bool(r.get("error"))) for r in client.reports] == [
        ("bad", True), ("ok", False)]


@pytest.mark.unit
def test_clean_failure_marks_shard_failed_on_server(tmp_path, monkeypatch):
    """실제 서버 서비스와 연결 — 오류 보고 후 샤드가 running에 고착되지 않는다."""
    from config.server_manager import save_servers
    from models.cleaning_schemas import (
        CleaningJobCreate,
        CleaningRecipeRequest,
        ShardReport,
    )
    from models.federated_schemas import SiloGroupRequest
    from services import cleaning_job_service, cleaning_recipe_service, silo_group_service

    save_servers({"silo-1": {"base_url": "tcp://x:1", "label": "silo-1", "type": "remote",
                             "role": "client", "tls": False}})
    silo_group_service.create_group(SiloGroupRequest(group_id="g", member_node_ids=["silo-1"]))
    cleaning_recipe_service.register_recipe(CleaningRecipeRequest(
        name="silo-hvc", version="1.0.0", steps=synthetic.HVC_STEPS,
        mapping=synthetic.HVC_MAPPING))
    cleaning_job_service.create_job(CleaningJobCreate(
        job_id="j1", recipe_name="silo-hvc", recipe_version="1.0.0", group_id="g",
        dataset_label="sources"))

    class _ServiceClient:
        def fetch_cleaning_recipe(self, name, version):
            return cleaning_recipe_service.get_recipe(name, version).model_dump()

        def start_cleaning_shard(self, job_id, shard_index):
            return cleaning_job_service.start_shard(job_id, shard_index, "silo-1").model_dump()

        def report_cleaning_shard(self, job_id, shard_index, rows_in, rows_out, step_counters,
                                  **kw):
            report = ShardReport(job_id=job_id, shard_index=shard_index, silo_id="silo-1",
                                 rows_in=rows_in, rows_out=rows_out,
                                 step_counters=step_counters, started_at="t", completed_at="t",
                                 **kw)
            return cleaning_job_service.report_shard(report).model_dump()

    monkeypatch.setattr(silo_worker, "SiloClient", lambda *_a, **_k: _ServiceClient())
    synthetic.write_sources("silo-1", tmp_path)
    (tmp_path / "entity.csv").write_text("eid,x3_level\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        silo_worker.run_clean(_args(tmp_path, recipe_name="silo-hvc"))

    job = cleaning_job_service.get_job("j1")
    assert job.shards[0].status == "failed" and job.status == "failed"
    assert "공통 스키마" in job.shards[0].error
