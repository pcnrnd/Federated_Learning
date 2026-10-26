"""engine=flower 작업 — 엔진 선택 API, 실행 제출·상태·취소·실패 기록, 결과의 기존 기록 반영.

실제 SuperLink 대신 FakeFlower가 flwr CLI(_cli) 자리를 맡는다. `run`은 실제 ClientApp(train_reply)과
ServerApp(summarize·write_result) 함수로 결과 파일을 써서, Flower 전송만 빼고 같은 계산을 거친다.
실제 Flower 실행은 tests/test_flower_live.py(flower_live 마커, dts 시험에서만).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("flwr")

from flower_app import client_app, server_app  # noqa: E402
from models.federated_schemas import LiveLearning, ParameterContribution, TrainingJobRequest, TrainingRound  # noqa: E402
from services import flower_engine  # noqa: E402
from services import training_job_service as jobs  # noqa: E402
from services import training_round_service as rounds  # noqa: E402
from silo_sdk import training_runtime  # noqa: E402
from silo_sdk.training_runtime import LiveWorker  # noqa: E402
from test_live_training import independent_step, seed  # noqa: E402


class FakeFlower:
    """flwr CLI 대역. ls --run-id마다 statuses를 하나씩 진행하고 마지막 상태에 머문다."""

    def __init__(self, data, statuses=("running", "finished:completed"), tamper=None, drop=()):
        self.data, self.statuses, self.tamper, self.drop = data, statuses, tamper, set(drop)
        self.runs: dict[int, list[str]] = {}
        self.calls: list[tuple] = []
        self.stopped: list[int] = []
        self.external: list[dict] = []

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == "run":
            round_dir = Path(args[-1].split("=", 1)[1].strip('"'))
            run_id = len(self.runs) + 1
            self.runs[run_id] = list(self.statuses)
            self.simulate(round_dir)
            return {"success": True, "run-id": str(run_id)}
        if args[0] == "ls" and "--run-id" in args:
            queue = self.runs[int(args[-1])]
            status = queue.pop(0) if len(queue) > 1 else queue[0]
            return {"success": True, "runs": [{"run-id": args[-1], "status": status, "status-details": "N/A"}]}
        if args[0] == "ls":
            return {"success": True, "runs": [{"status": q[0]} for q in self.runs.values()] + self.external}
        if args[0] == "stop":
            self.stopped.append(int(args[1]))
            self.runs[int(args[1])] = ["finished:stopped"]
            return {"success": True, "run-id": args[1]}
        raise AssertionError(args)

    def simulate(self, round_dir: Path) -> None:
        entry = json.loads((round_dir / "request.json").read_bytes())
        if self.tamper:
            self.tamper(entry)  # FL-5 장애 주입: ServerApp이 읽는 요청만 바꾸고 실제 데이터는 그대로
        body = json.dumps(entry)
        replies = []
        for silo, directory in self.data.items():
            if silo in self.drop:
                continue
            reply = client_app.train_reply(body, silo, str(directory))
            replies.append((reply["silo-id"], json.loads(reply["leaf"]) if "leaf" in reply else None,
                            reply.get("error")))
        result = server_app.summarize(entry, replies, connected=len(self.data) - len(self.drop))
        server_app.write_result(round_dir / "result.json", result)

    @property
    def submitted(self):
        return [call for call in self.calls if call[0] == "run"]


@pytest.fixture
def flower_env(tmp_path, monkeypatch):
    monkeypatch.setenv(flower_engine.ENV_SUPERLINK, "superlink:8000")
    monkeypatch.setenv(flower_engine.ENV_EXCHANGE, str(tmp_path / "exchange"))
    monkeypatch.setattr(jobs.resource_service, "group_has_pressure", lambda _nodes: False)
    return tmp_path


def flower_job(job_id="fl", **extra):
    return jobs.create_job(TrainingJobRequest(job_id=job_id, model_name="m", version="1.0.0", group_id="root",
        cleaning_job_id="cleaned", learning=LiveLearning(), engine="flower",
        min_contributions=extra.pop("min_contributions", 2), max_rounds=extra.pop("max_rounds", 1), **extra))


def run_round(fake, monkeypatch):
    """제출 → running → finished 처리까지 Flower tick을 돌린다."""
    monkeypatch.setattr(flower_engine, "_cli", fake)
    for _ in range(4):
        flower_engine.tick()


# ── FL-1·FL-8: 엔진 선택 API ──────────────────────────────────────────────

def test_engine_defaults_to_native_and_old_records_still_load(tmp_path, monkeypatch):
    seed(tmp_path, count=2, hierarchy=False)
    monkeypatch.delenv(flower_engine.ENV_SUPERLINK, raising=False)
    from main import app
    response = TestClient(app).post("/api/training-jobs", json={"job_id": "old", "model_name": "m",
        "version": "1.0.0", "group_id": "root"})
    assert response.status_code == 201 and response.json()["engine"] == "native"
    old_round = {"round_id": "r", "model_name": "m", "version": "1", "group_id": "g", "min_contributions": 1,
                 "status": "open", "created_at": "2026-10-01T00:00:00+00:00"}
    assert TrainingRound(**old_round).engine == "native"
    assert TrainingRound(**old_round).flower_run_id is None


def test_flower_job_rejected_without_superlink_address(tmp_path, monkeypatch):
    seed(tmp_path, count=2, hierarchy=False)
    monkeypatch.delenv(flower_engine.ENV_SUPERLINK, raising=False)
    from main import app
    api = TestClient(app)
    body = {"job_id": "fl", "model_name": "m", "version": "1.0.0", "group_id": "root",
            "cleaning_job_id": "cleaned", "learning": {}, "engine": "flower"}
    rejected = api.post("/api/training-jobs", json=body)
    assert rejected.status_code == 422 and flower_engine.ENV_SUPERLINK in rejected.json()["detail"]
    assert api.post("/api/training-jobs", json={**body, "engine": "native"}).status_code == 201
    assert api.post("/api/training-jobs", json={**body, "job_id": "x", "engine": "tensorflow"}).status_code == 422


def test_flower_job_requires_live_learning(tmp_path, flower_env):
    seed(tmp_path, count=2, hierarchy=False)
    with pytest.raises(Exception) as rejected:
        jobs.create_job(TrainingJobRequest(job_id="fl", model_name="m", version="1.0.0", group_id="root",
                                           cleaning_job_id="cleaned", engine="flower"))
    assert rejected.value.status_code == 422


# ── FL-6: 사일로 워커가 Flower 라운드를 가져가지 않음 ─────────────────────────

def test_flower_round_hidden_from_worker_open_query_and_rejects_silo_writes(tmp_path, flower_env):
    seed(tmp_path, count=2, hierarchy=False)
    job = flower_job()
    assert jobs.tick() == [job.job_id]
    round_id = jobs.get_job(job.job_id).current_round_id
    assert rounds.get_round(round_id).engine == "flower"
    from main import app
    api = TestClient(app)
    assert [r["round_id"] for r in api.get("/api/training-rounds?status=open").json()] == []
    assert round_id in [r["round_id"] for r in api.get("/api/training-rounds").json()]
    contribution = {"round_id": round_id, "silo_id": "silo-1", "sample_count": 1, "parameters": [0, 0, 0, 0]}
    assert api.post(f"/api/training-rounds/{round_id}/contributions", json=contribution).status_code == 409
    failure = {"silo_id": "silo-1", "error_code": "input_missing"}
    assert api.post(f"/api/training-rounds/{round_id}/execution-errors", json=failure).status_code == 409
    assert rounds.get_round(round_id).status == "open"


# ── 끝까지: 결과가 자체 엔진과 같은 기여·집계(ridge-v1)·모델 기록이 됨 ─────────

def test_flower_rounds_record_like_native_and_chain(tmp_path, flower_env, monkeypatch):
    ids, roots, data, local_rows = seed(tmp_path)  # 2단 계층(대표 2 + 하위 4)
    all_rows = [row for rows in local_rows.values() for row in rows]
    fake = FakeFlower(data)
    monkeypatch.setattr(flower_engine, "_cli", fake)
    job = flower_job(max_rounds=2)
    base, previous = [0.0] * 4, None
    for occurrence in (1, 2):
        assert jobs.tick() == [job.job_id]
        round_id = jobs.get_job(job.job_id).current_round_id
        assert flower_engine.tick() == [round_id]  # 제출
        assert flower_engine.tick() == []  # running
        assert flower_engine.tick() == [round_id]  # finished → 반영
        entry = rounds.get_round(round_id)
        assert entry.status == "completed" and entry.flower_run_id == occurrence
        assert entry.parent_round_id == previous and entry.base_parameters == base
        result = rounds.get_result(round_id)
        assert result.format == "ridge-v1" and result.total_samples == len(all_rows)
        assert result.parameters == pytest.approx(independent_step(all_rows, base), abs=1e-12)
        assert {c.silo_id for c in rounds.list_contributions(round_id)} == set(roots)
        assert {leaf["silo_id"] for leaf in result.origins} == set(ids)
        request = json.loads((tmp_path / "exchange" / round_id / "request.json").read_bytes())
        assert set(request) == set(flower_engine.REQUEST_FIELDS)
        base, previous = result.parameters, round_id
    jobs.tick()
    finished = jobs.get_job(job.job_id)
    assert (finished.status, finished.rounds_completed, finished.rounds_failed) == ("completed", 2, 0)
    from services.training_model_service import reconcile_completed_results
    assert set(reconcile_completed_results()) >= {previous}
    assert len(fake.submitted) == 2


def test_flower_matches_native_engine_within_tolerance(tmp_path, flower_env, monkeypatch):
    """FL-3 로컬 대응: 같은 정제 데이터·시작 가중치·설정에서 자체 엔진과 Flower 결과 비교 (Q4)."""
    ids, _roots, data, _rows = seed(tmp_path, count=3, hierarchy=False)

    class Local:
        def __init__(self, node):
            self.silo_id, self.api_key = node, None

        def push_live_parameters(self, envelope):
            return rounds.submit_contribution(ParameterContribution(**envelope)).model_dump()

    native = rounds.create_round(rounds.TrainingRoundCreate(model_name="m", version="1.0.0", group_id="root",
        cleaning_job_id="cleaned", min_contributions=3, learning=LiveLearning()))
    for node in ids:
        assert LiveWorker(Local(node), str(data[node])).process_round(native.model_dump())
    native_result = rounds.aggregate_round(native.round_id)
    flower_job(min_contributions=3)
    jobs.tick()
    run_round(FakeFlower(data), monkeypatch)
    flower_round = next(r for r in rounds.list_rounds(status="completed") if r.engine == "flower")
    flower_result = rounds.get_result(flower_round.round_id)
    error = max(abs(a - b) for a, b in zip(native_result.parameters, flower_result.parameters))
    print(json.dumps({"fl3_local_max_abs_error": error, "atol": flower_engine.AGGREGATE_ATOL}))
    assert error <= flower_engine.AGGREGATE_ATOL
    assert native_result.total_samples == flower_result.total_samples


# ── FL-7: 동시에 1개 ────────────────────────────────────────────────────

def test_only_one_flower_run_at_a_time(tmp_path, flower_env, monkeypatch):
    _ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    fake = FakeFlower(data, statuses=("running", "running", "finished:completed"))
    monkeypatch.setattr(flower_engine, "_cli", fake)
    first, second = flower_job("a"), flower_job("b")
    assert sorted(jobs.tick()) == ["a", "b"]
    flower_engine.tick()
    assert len(fake.submitted) == 1
    flower_engine.tick()
    flower_engine.tick()
    assert len(fake.submitted) == 1  # 앞 실행이 running인 동안 제출 없음
    flower_engine.tick()  # 앞 실행 finished → 반영 → 같은 tick에 다음 라운드 제출
    assert len(fake.submitted) == 2
    done = [r for r in rounds.list_rounds() if r.job_id in (first.job_id, second.job_id) and r.status == "completed"]
    assert len(done) == 1


def test_external_unfinished_run_blocks_submission(tmp_path, flower_env, monkeypatch):
    _ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    fake = FakeFlower(data)
    fake.external = [{"status": "running"}]  # 백엔드 밖에서 제출된 실행 / 재시작 전 고아 실행
    monkeypatch.setattr(flower_engine, "_cli", fake)
    flower_job()
    jobs.tick()
    flower_engine.tick()
    assert fake.submitted == []
    fake.external = [{"status": "finished:completed"}]
    flower_engine.tick()
    assert len(fake.submitted) == 1


# ── FL-4: 일시정지·재개·취소 ─────────────────────────────────────────────

def test_pause_holds_submission_and_resume_continues(tmp_path, flower_env, monkeypatch):
    _ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    fake = FakeFlower(data)
    monkeypatch.setattr(flower_engine, "_cli", fake)
    job = flower_job()
    jobs.tick()
    jobs.pause_job(job.job_id)
    flower_engine.tick()
    assert fake.submitted == []
    jobs.resume_job(job.job_id)
    run_round(fake, monkeypatch)
    assert len(fake.submitted) == 1
    jobs.tick()
    assert jobs.get_job(job.job_id).status == "completed"


def test_cancel_stops_running_run_and_records_reason(tmp_path, flower_env, monkeypatch):
    _ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    fake = FakeFlower(data, statuses=("running",))
    monkeypatch.setattr(flower_engine, "_cli", fake)
    job = flower_job()
    jobs.tick()
    round_id = jobs.get_job(job.job_id).current_round_id
    flower_engine.tick()
    jobs.cancel_job(job.job_id)
    flower_engine.tick()
    assert fake.stopped == [1]
    failed = rounds.get_round(round_id)
    assert failed.status == "failed" and "작업 취소" in failed.error


def test_cancel_before_submission_never_submits(tmp_path, flower_env, monkeypatch):
    _ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    fake = FakeFlower(data)
    monkeypatch.setattr(flower_engine, "_cli", fake)
    job = flower_job()
    jobs.tick()
    round_id = jobs.get_job(job.job_id).current_round_id
    jobs.cancel_job(job.job_id)
    flower_engine.tick()
    assert fake.submitted == [] and rounds.get_round(round_id).status == "failed"


# ── FL-5·FL-9 로컬: 실패는 원인과 함께 기록 ────────────────────────────────

def test_hash_mismatch_fails_round_without_training(tmp_path, flower_env, monkeypatch):
    _ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    trained = []
    original = training_runtime.train_iterative_ridge
    monkeypatch.setattr(training_runtime, "train_iterative_ridge",
                        lambda rows, *a, **k: trained.append(len(rows)) or original(rows, *a, **k))

    def tamper(entry):
        entry["cleaning_snapshot"]["silo-2"]["output_hash"] = "0" * 64

    job = flower_job()
    jobs.tick()
    round_id = jobs.get_job(job.job_id).current_round_id
    run_round(FakeFlower(data, statuses=("finished:failed",), tamper=tamper), monkeypatch)
    failed = rounds.get_round(round_id)
    assert failed.status == "failed" and "silo-2=invalid_model_or_input" in failed.error
    assert failed.execution_errors["silo-2"]["error_code"] == "invalid_model_or_input"
    assert len(trained) == 1  # silo-1만 학습, 해시가 다른 silo-2는 학습 0
    jobs.tick()
    assert jobs.get_job(job.job_id).rounds_failed == 1


def test_missing_supernode_fails_with_reason(tmp_path, flower_env, monkeypatch):
    _ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    job = flower_job()
    jobs.tick()
    round_id = jobs.get_job(job.job_id).current_round_id
    run_round(FakeFlower(data, statuses=("finished:failed",), drop={"silo-2"}), monkeypatch)
    failed = rounds.get_round(round_id)
    assert "SuperNode 연결 1/2" in failed.error and "silo-2=no_reply" in failed.error


def test_timeout_stops_run_and_fails(tmp_path, flower_env, monkeypatch):
    _ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    fake = FakeFlower(data, statuses=("running",))
    monkeypatch.setattr(flower_engine, "_cli", fake)
    job = flower_job()
    jobs.tick()
    round_id = jobs.get_job(job.job_id).current_round_id
    flower_engine.tick()
    monkeypatch.setenv(flower_engine.ENV_TIMEOUT, "0")
    flower_engine.tick()
    assert fake.stopped == [1] and "제한 시간 0s 초과" in rounds.get_round(round_id).error


def test_completed_status_without_result_or_bad_aggregate_fails(tmp_path, flower_env, monkeypatch):
    _ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)

    class Corrupt(FakeFlower):
        def simulate(self, round_dir):
            super().simulate(round_dir)
            result = json.loads((round_dir / "result.json").read_bytes())
            result["aggregate"] = [value + 1.0 for value in result["aggregate"]]
            server_app.write_result(round_dir / "result.json", result)

    flower_job("a")
    jobs.tick()
    run_round(Corrupt(data), monkeypatch)
    bad = rounds.list_rounds(status="failed")
    assert len(bad) == 1 and "허용오차" in bad[0].error

    class NoResult(FakeFlower):
        def simulate(self, round_dir):
            pass

    flower_job("b")
    jobs.tick()
    run_round(NoResult(data), monkeypatch)
    assert any("결과 파일 없음" in (r.error or "") for r in rounds.list_rounds(status="failed"))


def test_status_check_errors_are_retried_then_time_out(tmp_path, flower_env, monkeypatch):
    _ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    fake = FakeFlower(data, statuses=("running",))
    monkeypatch.setattr(flower_engine, "_cli", fake)
    job = flower_job()
    jobs.tick()
    round_id = jobs.get_job(job.job_id).current_round_id
    flower_engine.tick()

    def down(*args):
        raise flower_engine.FlowerCliError("flwr ls: connection refused")

    monkeypatch.setattr(flower_engine, "_cli", down)
    assert flower_engine.tick() == []
    assert rounds.get_round(round_id).status == "open"
    monkeypatch.setenv(flower_engine.ENV_TIMEOUT, "0")
    flower_engine.tick()
    assert "상태 확인 실패" in rounds.get_round(round_id).error


def test_submit_failure_and_missing_address_handling(tmp_path, flower_env, monkeypatch):
    _ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)

    def refuse(*args):
        if args[0] == "ls":
            return {"success": True, "runs": []}
        raise flower_engine.FlowerCliError("flwr run: Failed to start run")

    monkeypatch.setattr(flower_engine, "_cli", refuse)
    job = flower_job()
    jobs.tick()
    round_id = jobs.get_job(job.job_id).current_round_id
    monkeypatch.delenv(flower_engine.ENV_SUPERLINK)
    assert flower_engine.tick() == []  # 주소가 빠지면 열린 라운드는 대기
    monkeypatch.setenv(flower_engine.ENV_SUPERLINK, "superlink:8000")
    assert flower_engine.tick() == [round_id]
    assert "제출 실패" in rounds.get_round(round_id).error


# ── flwr CLI JSON 처리 (Q1) ─────────────────────────────────────────────

class _Proc:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def test_cli_judges_success_field_not_exit_code(tmp_path, monkeypatch):
    monkeypatch.setenv(flower_engine.ENV_SUPERLINK, "superlink:8000")
    monkeypatch.setenv(flower_engine.ENV_HOME, str(tmp_path / "home"))
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(command=command, env=kwargs["env"])
        return outputs.pop(0)

    outputs = [
        _Proc('{\n  "success": true,\n  "run-id": "77",\n  "fab-hash": "abc"\n}\n'),
        _Proc('{"success": false, "error-message": "SuperLink\\nunreachable"}'),  # JSON 모드 실패도 exit 0
        _Proc("Traceback ...", returncode=1, stderr="boom"),
        _Proc('{"success": true, "runs": [{"run-id": "77", "status": "finished:failed", "status-details": "x"}]}'),
        _Proc('{"success": true, "run-id": "77"}'),
    ]
    monkeypatch.setattr(flower_engine.subprocess, "run", fake_run)
    assert flower_engine._cli("run", "app", "fed")["run-id"] == "77"
    assert seen["command"][-2:] == ["--format", "json"]
    assert seen["env"]["FLWR_HOME"] == str(tmp_path / "home")
    config = (tmp_path / "home" / "config.toml").read_text(encoding="utf-8")
    assert 'default = "fed"' in config and 'address = "superlink:8000"' in config and "insecure = true" in config
    with pytest.raises(flower_engine.FlowerCliError, match="SuperLink unreachable"):
        flower_engine._cli("ls", "fed")
    with pytest.raises(flower_engine.FlowerCliError, match="boom"):
        flower_engine._cli("ls", "fed")
    assert flower_engine.run_status(77) == ("finished:failed", "x")
    flower_engine.stop_run(77)
    assert seen["command"][1:4] == ["stop", "77", "fed"]


def test_cli_process_errors_and_empty_ls(tmp_path, monkeypatch):
    monkeypatch.setenv(flower_engine.ENV_HOME, str(tmp_path / "home"))

    def missing(command, **kwargs):
        raise FileNotFoundError("flwr")

    monkeypatch.setattr(flower_engine.subprocess, "run", missing)
    with pytest.raises(flower_engine.FlowerCliError, match="FileNotFoundError"):
        flower_engine._cli("ls", "fed")
    monkeypatch.setattr(flower_engine, "_cli", lambda *a: {"success": True, "runs": []})
    with pytest.raises(flower_engine.FlowerCliError, match="없음"):
        flower_engine.run_status(5)
    assert flower_engine._parse_json("no json") == {} and flower_engine._parse_json("{broken") == {}
    assert flower_engine._parse_json("[1]") == {}
    monkeypatch.setenv(flower_engine.ENV_TIMEOUT, "abc")
    assert flower_engine._timeout_seconds() == flower_engine.DEFAULT_TIMEOUT_SECONDS
