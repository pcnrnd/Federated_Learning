"""정제 → 학습 연결 (F6) — 레시피를 지정하면 로컬 원천 정제 결과가 릿지 학습 입력이 된다"""
from __future__ import annotations

import argparse
import json
import math

import pytest

from scripts import silo_worker
from silo_sdk import synthetic

RECIPE = {"steps": synthetic.HVC_STEPS, "mapping": synthetic.HVC_MAPPING}


class _TrainClient:
    """레시피 조회·기여 push·라운드 폴링 대역"""

    def __init__(self, rounds: list | None = None) -> None:
        self.pushes: list[dict] = []
        self.metrics: list[tuple] = []
        self.rounds = rounds or []
        self.list_calls = 0

    def fetch_cleaning_recipe(self, name, version):
        assert (name, version) == ("silo-hvc", "1.0.0")
        return RECIPE

    def get_round(self, round_id):
        return next((r for r in self.rounds if r["round_id"] == round_id), {"round_id": round_id})

    def push_parameters(self, round_id, sample_count, parameters, **kwargs):
        self.pushes.append({"round_id": round_id, "sample_count": sample_count,
                            "parameters": parameters, **kwargs})
        return {"parameter_dim": len(parameters), "aggregated_from": kwargs.get(
            "aggregated_from", [])}

    def list_rounds(self, *, status=None, model_name=None):
        self.list_calls += 1
        return self.rounds if self.list_calls == 1 else []

    def push_metric(self, model_name, version, metric, value):
        self.metrics.append((metric, value))
        return {}


def _args(tmp_path, **extra) -> argparse.Namespace:
    base = dict(central="http://c", silo_id="silo-3", round_id="r1", recipe_name="silo-hvc",
                recipe_version="1.0.0", data_dir=str(tmp_path), emit_only=False)
    return argparse.Namespace(**{**base, **extra})


def _install(monkeypatch, client) -> None:
    monkeypatch.setattr(silo_worker, "SiloClient", lambda *_a, **_k: client)


@pytest.mark.unit
def test_train_with_recipe_learns_from_cleaned_local_sources(tmp_path, monkeypatch, capsys):
    seen: dict = {}
    real_train = silo_worker.train_ridge

    def spy(rows, *args, **kwargs):
        seen["rows"] = list(rows)
        return real_train(seen["rows"], *args, **kwargs)

    monkeypatch.setattr(silo_worker, "train_ridge", spy)
    client = _TrainClient()
    _install(monkeypatch, client)

    silo_worker.run_train(_args(tmp_path))

    rows_in, cleaned, _ = silo_worker.clean_local("silo-3", str(tmp_path), RECIPE)
    assert seen["rows"] == cleaned  # 정제 결과가 그대로 학습 입력
    push = client.pushes[0]
    assert push["sample_count"] == len(cleaned) == push["rows_after_cleaning"]
    assert push["rows_before_cleaning"] == rows_in > push["rows_after_cleaning"]
    assert 0 < push["train_rmse"] < 0.2
    assert push["parameters"] == pytest.approx(
        [*synthetic.TRUE_WEIGHTS, synthetic.TRUE_BIAS], abs=0.05)
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["rows_after_cleaning"] == len(cleaned)


@pytest.mark.unit
def test_train_without_recipe_keeps_legacy_rows_and_payload(tmp_path, monkeypatch):
    client = _TrainClient()
    _install(monkeypatch, client)

    silo_worker.run_train(argparse.Namespace(central="http://c", silo_id="silo-3",
                                             round_id="r1"))

    push = client.pushes[0]
    assert push["sample_count"] == len(silo_worker._local_train_rows("silo-3"))
    assert set(push) == {"round_id", "sample_count", "parameters"}
    assert not (tmp_path / "period_a.csv").exists()


@pytest.mark.unit
def test_recipe_name_and_version_go_together(tmp_path, monkeypatch):
    _install(monkeypatch, _TrainClient())
    with pytest.raises(SystemExit, match="함께"):
        silo_worker.run_train(_args(tmp_path, recipe_version=None))


@pytest.mark.unit
def test_train_emit_only_prints_child_record_without_push(tmp_path, monkeypatch, capsys):
    client = _TrainClient()
    _install(monkeypatch, client)

    silo_worker.run_train(_args(tmp_path, emit_only=True, round_id=None))

    assert client.pushes == []
    child = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert set(child) >= {"silo_id", "sample_count", "parameters", "rows_before_cleaning",
                          "rows_after_cleaning", "train_rmse"}


@pytest.mark.unit
def test_train_loop_with_recipe_pushes_cleaning_stats_each_round(tmp_path, monkeypatch):
    rounds = [{"round_id": "r1", "model_name": "m", "version": "1", "contributors": []}]
    client = _TrainClient(rounds)
    _install(monkeypatch, client)
    monkeypatch.setattr(silo_worker.time, "sleep", lambda _s: None)

    silo_worker.run_train_loop(_args(tmp_path, model="m", max_rounds=1, poll_interval=0,
                                     max_idle=5.0))

    push = client.pushes[0]
    assert push["rows_after_cleaning"] == push["sample_count"]
    assert client.metrics and 0.99 < client.metrics[0][1] <= 1.0  # 정제 데이터 R²


@pytest.mark.unit
def test_train_edge_with_recipe_combines_cleaning_stats(tmp_path, monkeypatch, capsys):
    children = []
    for silo_id in ("silo-4", "silo-5"):
        _install(monkeypatch, _TrainClient())
        silo_worker.run_train(_args(tmp_path / silo_id, silo_id=silo_id, emit_only=True))
        children.append(json.loads(capsys.readouterr().out.strip().splitlines()[-1]))
    path = tmp_path / "children.json"
    path.write_text(json.dumps(children), encoding="utf-8")
    client = _TrainClient()
    _install(monkeypatch, client)

    silo_worker.run_train_edge(_args(tmp_path / "silo-3", children_json=str(path)))

    push = client.pushes[0]
    own = silo_worker.clean_local("silo-3", str(tmp_path / "silo-3"), RECIPE)
    assert push["rows_after_cleaning"] == len(own[1]) + sum(
        c["rows_after_cleaning"] for c in children) == push["sample_count"]
    assert push["rows_before_cleaning"] == own[0] + sum(c["rows_before_cleaning"]
                                                        for c in children)
    assert push["aggregated_from"] == ["silo-4", "silo-5"]
    assert 0 < push["train_rmse"] < 0.2


@pytest.mark.unit
def test_train_edge_omits_stats_when_a_child_has_none(tmp_path, monkeypatch, capsys):
    child = {"silo_id": "silo-4", "sample_count": 10, "parameters": [2.0, -3.0, 0.5, 4.0]}
    path = tmp_path / "children.json"
    path.write_text(json.dumps([child]), encoding="utf-8")
    client = _TrainClient()
    _install(monkeypatch, client)

    silo_worker.run_train_edge(_args(tmp_path, children_json=str(path)))

    assert "rows_after_cleaning" not in client.pushes[0]


@pytest.mark.unit
def test_rmse_matches_definition():
    rows = [{"x1": 1.0, "x2": 0.0, "x3": 0.0, "y": 3.0}, {"x1": 0.0, "x2": 0.0, "x3": 0.0,
                                                         "y": 0.0}]
    # 예측 y = 2*x1 + 0 → 오차 [1, 0]
    assert silo_worker._rmse(rows, [2.0, 0.0, 0.0, 0.0]) == pytest.approx(math.sqrt(0.5))


@pytest.mark.unit
def test_client_payload_adds_cleaning_stats_only_when_given(monkeypatch):
    from silo_sdk import SiloClient

    sent: list[dict] = []
    client = SiloClient("http://c", "silo-1")
    monkeypatch.setattr(client, "_request", lambda method, path, body=None, **kw: sent.append(
        body) or {})

    client.push_parameters("r1", 10, [1.0])
    client.push_parameters("r1", 10, [1.0], rows_before_cleaning=20, rows_after_cleaning=10,
                           train_rmse=0.1)

    assert set(sent[0]) == {"round_id", "silo_id", "sample_count", "parameters", "checksum",
                            "aggregated_from"}
    assert sent[1]["rows_before_cleaning"] == 20 and sent[1]["train_rmse"] == 0.1


@pytest.mark.unit
def test_train_loop_uses_recipe_of_round_linked_cleaning_job(tmp_path, monkeypatch):
    from silo_sdk import cleaning_output
    synthetic.write_sources("silo-3", tmp_path)
    manifest = cleaning_output.execute(str(tmp_path), "silo-3",
        {"job_id": "c1", "dataset_label": "silo-sources"},
        {"shard_index": 0, "attempt_id": "linked"}, RECIPE)
    # 성공 스냅샷 뒤 원천 변경: 연결 학습은 기존 결과를 사용해야 한다.
    (tmp_path / "period_a.csv").write_text("changed source", encoding="utf-8")
    rounds = [
        {"round_id": "r1", "model_name": "m", "version": "1", "contributors": [],
         "cleaning_job_id": "c1"},
        {"round_id": "r2", "model_name": "m", "version": "1", "contributors": []},
    ]

    class _LinkedClient(_TrainClient):
        jobs_fetched: list[str] = []

        def get_cleaning_job(self, job_id):
            self.jobs_fetched.append(job_id)
            return {"job_id": job_id, "status": "completed", "shards": [
                {**manifest, "silo_id": "silo-3", "status": "completed"}]}

    client = _LinkedClient(rounds)
    _install(monkeypatch, client)
    monkeypatch.setattr(silo_worker.time, "sleep", lambda _s: None)

    silo_worker.run_train_loop(_args(tmp_path, recipe_name=None, recipe_version=None, model="m",
                                     max_rounds=2, poll_interval=0, max_idle=5.0))

    by_round = {p["round_id"]: p for p in client.pushes}
    assert client.jobs_fetched == ["c1"]
    assert by_round["r1"]["rows_after_cleaning"] == by_round["r1"]["sample_count"]
    assert "rows_after_cleaning" not in by_round["r2"]  # 연결 없는 라운드는 기존 동작
    assert by_round["r2"]["sample_count"] == len(silo_worker._local_train_rows("silo-3"))


@pytest.mark.unit
def test_train_loop_survives_transient_error_fetching_linked_job(tmp_path, monkeypatch, capsys):
    from silo_sdk.client import SiloClientError

    rounds = [{"round_id": "r1", "model_name": "m", "version": "1", "contributors": [],
               "cleaning_job_id": "c1"}]

    class _Flaky(_TrainClient):
        def get_cleaning_job(self, job_id):
            raise SiloClientError(503, "busy")

    client = _Flaky(rounds)
    _install(monkeypatch, client)
    monkeypatch.setattr(silo_worker.time, "sleep", lambda _s: None)

    silo_worker.run_train_loop(_args(tmp_path, recipe_name=None, recipe_version=None, model="m",
                                     max_rounds=1, poll_interval=0, max_idle=0.05))

    events = [json.loads(x).get("event") for x in capsys.readouterr().out.strip().splitlines()]
    assert "transient_error" in events and events[-1] == "idle_timeout"
    assert client.pushes == []


def test_linked_snapshot_needs_no_original_sources_or_eager_fallback_recipe(tmp_path, monkeypatch):
    from silo_sdk import cleaning_output
    files = synthetic.write_sources("silo-3", tmp_path)
    manifest = cleaning_output.execute(str(tmp_path), "silo-3",
        {"job_id": "c1", "dataset_label": "silo-sources"},
        {"shard_index": 0, "attempt_id": "linked"}, RECIPE)
    for path in files.values():
        path.unlink()
    class Linked(_TrainClient):
        def get_cleaning_job(self, _identity):
            return {"status": "completed", "shards": [{**manifest, "silo_id": "silo-3", "status": "completed"}]}

    client = Linked([{"round_id": "r1", "model_name": "m", "version": "1",
                      "contributors": [], "cleaning_job_id": "c1"}])
    _install(monkeypatch, client)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("연결 출력 학습 전에 원천을 읽거나 재정제하면 안 됨")
    monkeypatch.setattr(silo_worker, "clean_local", forbidden)
    silo_worker.run_train_loop(_args(tmp_path, model="m", max_rounds=1, poll_interval=0, max_idle=1))
    assert client.pushes[0]["sample_count"] == manifest["rows_out"]
    assert not any(path.exists() for path in files.values())


@pytest.mark.unit
def test_train_loop_stops_on_missing_linked_job(tmp_path, monkeypatch):
    from silo_sdk.client import SiloClientError

    rounds = [{"round_id": "r1", "model_name": "m", "version": "1", "contributors": [],
               "cleaning_job_id": "ghost"}]

    class _Missing(_TrainClient):
        def get_cleaning_job(self, job_id):
            raise SiloClientError(404, "없음")

    _install(monkeypatch, _Missing(rounds))
    monkeypatch.setattr(silo_worker.time, "sleep", lambda _s: None)

    with pytest.raises(SiloClientError):
        silo_worker.run_train_loop(_args(tmp_path, recipe_name=None, recipe_version=None,
                                         model="m", max_rounds=1, poll_interval=0, max_idle=1))


@pytest.mark.unit
def test_edge_stats_ignore_children_with_null_values():
    child = {"silo_id": "s", "sample_count": 1, "parameters": [0.0],
             "rows_before_cleaning": None, "rows_after_cleaning": 1, "train_rmse": 0.1}
    own = {"rows_before_cleaning": 2, "rows_after_cleaning": 1, "train_rmse": 0.1}

    assert silo_worker._edge_cleaning_stats(own, 1, [child]) == {}
