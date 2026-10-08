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
