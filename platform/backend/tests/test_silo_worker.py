"""사일로 E2E 워커(scripts/silo_worker.py)

- monitor 내성 / train-loop 409 원인 구분
- train-edge(엣지 집계자 모드) — 자기 표본 포함 여부
"""
from __future__ import annotations

import argparse
import json
import urllib.error

import pytest

from scripts import silo_worker
from silo_sdk.client import SiloClientError


class _FakeClient:
    """push 결과를 스크립트로 재생하는 SiloClient 대역."""

    def __init__(self, outcomes: list, *, rounds: list | None = None,
                 round_lookup: dict | None = None) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0
        self.metrics: list[tuple] = []
        self.rounds = rounds if rounds is not None else []
        self.round_lookup = round_lookup or {}
        self.list_calls = 0

    def _next(self):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else {}
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def push_resource_sample(self, cpu, mem, *, disk_pct=None):
        return self._next()

    def push_parameters(self, round_id, sample_count, parameters):
        return self._next()

    def list_rounds(self, *, status=None, model_name=None):
        self.list_calls += 1
        # 첫 폴링에만 라운드를 돌려주고 이후에는 비운다 → idle timeout으로 종료
        return self.rounds if self.list_calls == 1 else []

    def get_round(self, round_id):
        entry = self.round_lookup.get(round_id)
        if entry is None:
            raise SiloClientError(404, "gone")
        return entry

    def push_metric(self, model_name, version, metric, value):
        self.metrics.append((model_name, version, metric, value))
        return {}


@pytest.fixture
def quiet_probes(monkeypatch):
    monkeypatch.setattr(silo_worker, "_cpu_pct", lambda: 10.0)
    monkeypatch.setattr(silo_worker, "_mem_pct", lambda: 20.0)
    monkeypatch.setattr(silo_worker, "_disk_pct", lambda: 30.0)
    monkeypatch.setattr(silo_worker.time, "sleep", lambda _s: None)


def _install(monkeypatch, fake: _FakeClient) -> None:
    monkeypatch.setattr(silo_worker, "SiloClient", lambda *_a, **_k: fake)


def _monitor_args(count: int, max_failures: int = 12) -> argparse.Namespace:
    return argparse.Namespace(central="http://c", silo_id="silo-1", interval=0,
                              count=count, max_failures=max_failures)


def _events(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]


@pytest.mark.unit
def test_monitor_recovers_after_transient_failures(quiet_probes, monkeypatch, capsys):
    fake = _FakeClient([
        urllib.error.URLError("connection refused"),
        SiloClientError(503, "backend restarting"),
        {},  # 성공
        {},
    ])
    _install(monkeypatch, fake)

    silo_worker.run_monitor(_monitor_args(count=2, max_failures=3))

    events = _events(capsys)
    assert [e.get("event") for e in events[:2]] == ["transient_error", "transient_error"]
    assert events[1]["failures"] == 2
    assert [e["pushed"] for e in events[2:]] == [1, 2]
    assert fake.calls == 4


@pytest.mark.unit
def test_monitor_failure_counter_resets_on_success(quiet_probes, monkeypatch, capsys):
    # 실패·성공 교대 — 연속 실패가 max_failures(2)에 닿지 않으므로 완주해야 한다
    fake = _FakeClient([
        TimeoutError(), {}, TimeoutError(), {}, TimeoutError(), {},
    ])
    _install(monkeypatch, fake)

    silo_worker.run_monitor(_monitor_args(count=3, max_failures=2))

    assert [e["failures"] for e in _events(capsys) if e.get("event")] == [1, 1, 1]
    assert fake.calls == 6


@pytest.mark.unit
def test_monitor_exits_after_bounded_consecutive_failures(quiet_probes, monkeypatch):
    fake = _FakeClient([urllib.error.URLError("down")] * 5)
    _install(monkeypatch, fake)

    with pytest.raises(SystemExit):
        silo_worker.run_monitor(_monitor_args(count=0, max_failures=3))
    assert fake.calls == 3


@pytest.mark.unit
def test_monitor_fails_fast_on_permanent_4xx(quiet_probes, monkeypatch):
    fake = _FakeClient([SiloClientError(422, "bad payload"), {}])
    _install(monkeypatch, fake)

    with pytest.raises(SiloClientError):
        silo_worker.run_monitor(_monitor_args(count=2))
    assert fake.calls == 1  # 재시도 없이 즉시 종료


@pytest.mark.unit
def test_monitor_fails_fast_on_coding_error(quiet_probes, monkeypatch):
    fake = _FakeClient([KeyError("cpu_pct")])
    _install(monkeypatch, fake)

    with pytest.raises(KeyError):
        silo_worker.run_monitor(_monitor_args(count=1))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("exc", "transient"),
    [
        (urllib.error.URLError("x"), True),
        (TimeoutError(), True),
        (SiloClientError(429, "slow down"), True),
        (SiloClientError(500, "boom"), True),
        (SiloClientError(400, "bad"), False),
        (SiloClientError(404, "missing"), False),
        (ValueError("bug"), False),
    ],
)
def test_is_transient_classification(exc, transient):
    assert silo_worker._is_transient(exc) is transient


# ---------- train-loop: 409 원인 구분 (진짜 중복 vs 라운드 마감 후 기여) ----------


def _loop_args() -> argparse.Namespace:
    return argparse.Namespace(central="http://c", silo_id="silo-1", model="m",
                              max_rounds=1, poll_interval=0, max_idle=0.05)


def _open_round(round_id: str) -> dict:
    return {"round_id": round_id, "model_name": "m", "version": "1.0.0",
            "status": "open", "contributors": []}


@pytest.mark.unit
def test_train_loop_409_after_round_closed_does_not_count_or_push_metric(
    quiet_probes, monkeypatch, capsys
):
    # push 시점엔 라운드가 이미 aggregating/completed → 409, 재조회에 내 기여 없음
    fake = _FakeClient(
        [SiloClientError(409, "라운드 상태가 'completed'이므로 기여를 받을 수 없습니다")],
        rounds=[_open_round("r1")],
        round_lookup={"r1": {**_open_round("r1"), "status": "completed",
                             "contributors": ["silo-2", "silo-3"]}},
    )
    _install(monkeypatch, fake)

    silo_worker.run_train_loop(_loop_args())

    events = _events(capsys)
    assert any(e.get("event") == "round_closed" and e["round_id"] == "r1" for e in events)
    assert fake.metrics == []  # 기여 미반영 라운드의 accuracy를 중복 집계하지 않는다
    final = events[-1]
    assert final["event"] == "idle_timeout" and final["contributed"] == 0


@pytest.mark.unit
def test_train_loop_409_real_duplicate_counts_once_and_pushes_metric_once(
    quiet_probes, monkeypatch, capsys
):
    # 이전 push가 타임아웃 뒤 서버에 반영된 경우 — 재조회 contributors에 내가 있다
    fake = _FakeClient(
        [SiloClientError(409, "사일로 'silo-1'는 이미 기여하였습니다")],
        rounds=[_open_round("r1")],
        round_lookup={"r1": {**_open_round("r1"), "contributors": ["silo-1"]}},
    )
    _install(monkeypatch, fake)

    silo_worker.run_train_loop(_loop_args())

    events = _events(capsys)
    assert events[-1]["event"] == "completed" and events[-1]["contributed"] == 1
    assert len(fake.metrics) == 1 and fake.metrics[0][2] == "accuracy"


# ---------- train-edge (엣지 집계자 모드) ----------


class _RecordingClient:
    """push_parameters 인자를 그대로 붙잡는 SiloClient 대역."""

    def __init__(self) -> None:
        self.pushed: dict = {}

    def push_parameters(self, round_id, sample_count, parameters, *,
                        aggregated_from=None, **_kw):
        self.pushed = {
            "round_id": round_id,
            "sample_count": sample_count,
            "parameters": parameters,
            "aggregated_from": list(aggregated_from or []),
        }
        return {"aggregated_from": self.pushed["aggregated_from"]}


def _edge_args(children_path: str) -> argparse.Namespace:
    return argparse.Namespace(
        central="http://central:8000",
        silo_id="silo-2",
        round_id="r1",
        children_json=children_path,
    )


def _child(silo_id: str) -> dict:
    """하위 사일로의 실제 로컬 학습 결과 — 드라이버가 모아 넘겨주는 형식."""
    rows = silo_worker._local_train_rows(silo_id)
    result = silo_worker.train_ridge(rows, silo_worker.FEATURES, "y", l2=1e-6)
    return {
        "silo_id": silo_id,
        "sample_count": result.sample_count,
        "parameters": result.parameters,
    }


@pytest.mark.unit
def test_train_edge_includes_own_samples(tmp_path, monkeypatch, capsys):
    """L3 실측 형상 — 집계자 silo-2(400) + silo-3(500) + silo-4(600) = 1500.

    구 동작은 자기 400을 빼고 1100을 제출해 라운드 합계가 3300 대신 2900이 됐다.
    provenance는 하위 2건만 — 자기 자신을 넣으면 서버가 422로 거부한다.
    """
    children = [_child("silo-3"), _child("silo-4")]
    path = tmp_path / "children.json"
    path.write_text(json.dumps(children), encoding="utf-8")

    fake = _RecordingClient()
    monkeypatch.setattr(silo_worker, "SiloClient", lambda *_a, **_k: fake)

    silo_worker.run_train_edge(_edge_args(str(path)))

    assert fake.pushed["sample_count"] == 1500  # 400 + 500 + 600
    assert fake.pushed["aggregated_from"] == ["silo-3", "silo-4"]

    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["own_sample_count"] == 400
    assert out["edge_total"] == 1500


@pytest.mark.unit
def test_train_edge_matches_flat_aggregate(tmp_path, monkeypatch, capsys):
    """엣지 집계 결과가 세 사일로 평면 집계와 수치적으로 같다 (결합법칙)."""
    from services import fedavg_aggregator

    children = [_child("silo-3"), _child("silo-4")]
    path = tmp_path / "children.json"
    path.write_text(json.dumps(children), encoding="utf-8")

    fake = _RecordingClient()
    monkeypatch.setattr(silo_worker, "SiloClient", lambda *_a, **_k: fake)
    silo_worker.run_train_edge(_edge_args(str(path)))
    capsys.readouterr()

    mine = _child("silo-2")
    flat_params, flat_total = fedavg_aggregator.aggregate(
        [(c["silo_id"], c["sample_count"], c["parameters"]) for c in [mine, *children]]
    )

    assert fake.pushed["sample_count"] == flat_total
    assert fake.pushed["parameters"] == pytest.approx(flat_params)


@pytest.mark.unit
def test_train_edge_reads_children_from_stdin(tmp_path, monkeypatch, capsys):
    """`-` 이면 stdin에서 읽는다 — 드라이버가 파이프로 넘기는 경로."""
    import io as _io

    children = [_child("silo-3")]
    monkeypatch.setattr(silo_worker.sys, "stdin", _io.StringIO(json.dumps(children)))

    fake = _RecordingClient()
    monkeypatch.setattr(silo_worker, "SiloClient", lambda *_a, **_k: fake)

    silo_worker.run_train_edge(_edge_args("-"))

    assert fake.pushed["sample_count"] == 900  # silo-2 400 + silo-3 500
    assert fake.pushed["aggregated_from"] == ["silo-3"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    ["[]", '[{"silo_id": "silo-3", "sample_count": 500}]'],
    ids=["empty", "missing_field"],
)
def test_train_edge_rejects_malformed_children(tmp_path, payload):
    path = tmp_path / "children.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(SystemExit):
        silo_worker._load_children(str(path))


@pytest.mark.unit
def test_flat_train_path_sends_no_aggregated_from(monkeypatch, capsys):
    """평면 제출 경로는 불변 — aggregated_from 없이 자기 표본만 push한다."""
    captured: dict = {}

    class _FlatClient:
        def push_parameters(self, round_id, sample_count, parameters, **kwargs):
            captured.update(
                {"sample_count": sample_count, "kwargs": kwargs}
            )
            return {"parameter_dim": len(parameters)}

    monkeypatch.setattr(silo_worker, "SiloClient", lambda *_a, **_k: _FlatClient())
    silo_worker.run_train(
        argparse.Namespace(
            central="http://central:8000", silo_id="silo-2", round_id="r1"
        )
    )

    assert captured["sample_count"] == 400  # 자기 표본만
    assert captured["kwargs"] == {}
