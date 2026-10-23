"""G2-F1~F4: 동적 admission, 실제 execute 취소/회수, 오류 분류, 중단 복구."""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import HTTPException

from config.server_manager import save_servers
from models.cleaning_schemas import CleaningJobCreate, CleaningRecipeRequest, ShardProgress, ShardReport
from models.federated_schemas import SiloGroupRequest, TrainingRoundCreate
from services import cleaning_execution as runtime, cleaning_job_service as jobs
from services import cleaning_recipe_service as recipes, silo_group_service
from silo_sdk import synthetic, cleaning_runtime
from silo_sdk.client import SiloClientError


@pytest.fixture(autouse=True)
def seed(tmp_path):
    save_servers({"silo-1": {"base_url": "tcp://silo-1:2375", "role": "client"}})
    silo_group_service.create_group(SiloGroupRequest(group_id="g", member_node_ids=["silo-1"]))
    for name in ("r", "slow"):
        steps = synthetic.HVC_STEPS + ([{"type": "lowercase", "params": {"columns": ["id"]}}] if name == "slow" else [])
        recipes.register_recipe(CleaningRecipeRequest(name=name, version="1.0.0",
            steps=steps, mapping=synthetic.HVC_MAPPING))
    synthetic.write_sources("silo-1", tmp_path)


def create(identity, **extra):
    return jobs.create_job(CleaningJobCreate(job_id=identity, recipe_name=extra.pop("recipe_name", "r"),
        recipe_version="1.0.0", group_id="g", dataset_label="silo-sources", **extra))


def call(function, *args):
    try:
        return function(*args).model_dump()
    except HTTPException as exc:
        raise SiloClientError(exc.status_code, str(exc.detail)) from exc


class Bridge:
    silo_id = "silo-1"

    def __init__(self):
        self.claims, self.reports = [], []

    def list_assigned_shards(self, status):
        return [s.model_dump() for s in jobs.list_assigned_shards(self.silo_id, status)]

    def start_cleaning_shard(self, identity, index, claim_id):
        self.claims.append(identity)
        return call(jobs.start_shard, identity, index, self.silo_id, claim_id)

    def fetch_cleaning_recipe(self, name, version):
        return call(recipes.get_recipe, name, version)

    def cleaning_progress(self, identity, index, token, done, total, stage):
        return call(runtime.progress, identity, index, ShardProgress(silo_id=self.silo_id,
            attempt_id=token, processed_units=done, total_units=total, stage=stage))

    def report_cleaning_shard(self, identity, index, **fields):
        self.reports.append((identity, fields))
        fields.setdefault("started_at", runtime.now().isoformat())
        fields.setdefault("completed_at", runtime.now().isoformat())
        return call(jobs.report_shard, ShardReport(job_id=identity, shard_index=index,
                                                 silo_id=self.silo_id, **fields))


def capture_children(monkeypatch):
    children = []
    original = asyncio.create_subprocess_exec

    async def observed(*args, **kwargs):
        process = await original(*args, **kwargs)
        children.append(process)
        assert sum(p.returncode is None for p in children) <= 2
        # test-only gate: 본체에 stdin을 주기 전 외부 sampler의 PID/메모리 관측 ACK 대기.
        try:
            if ack_dir := os.environ.get("FED_G2_PROCESS_ACK_DIR"):
                ack = Path(ack_dir) / f"{process.pid}.seen"
                for _ in range(1000):
                    if ack.is_file():
                        break
                    await asyncio.sleep(0.01)
                else:
                    pytest.fail("외부 tree sampler가 child 관측을 확인하지 못함")
        except BaseException:
            await cleaning_runtime._stop_process(process)
            raise
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", observed)
    return children


def blocking_execute_command(marker: Path):
    # 실제 cleaning_output.execute가 원천을 읽은 뒤 내부 thread pool의 행 변환에 진입한다.
    # 테스트 process는 이 sleep을 풀지 않는다. terminate/reap만으로 완료해야 한다.
    code = "\n".join([
        "import time", "from pathlib import Path", "from silo_sdk import cleaning",
        f"marker = Path({str(marker)!r})", "def blocked(rows, params):",
        "    marker.write_text('entered', encoding='utf-8')", "    time.sleep(3600)",
        "    return rows, 0", "cleaning._SINGLE_TABLE_STEPS['lowercase'] = blocked",
        "from silo_sdk.cleaning_executor import main", "raise SystemExit(main())",
    ])
    return [sys.executable, "-u", "-c", code]


async def wait_entered(marker, task):
    for _ in range(500):
        if marker.is_file():
            return
        if task.done():
            await task
            pytest.fail("실제 execute 진입 전에 종료됨")
        await asyncio.sleep(0.01)
    pytest.fail("실제 execute 진입이 관측되지 않음")


def test_G2_F2_actual_execute_timeout_and_cancellation_reap_children(tmp_path, monkeypatch):
    children = capture_children(monkeypatch)
    normal_command = cleaning_runtime._executor_command
    bridge = Bridge()

    async def scenario():
        for mode in ("timeout", "cancel"):
            marker = tmp_path / f"{mode}-entered"
            identity = f"slow-{mode}"
            create(identity, recipe_name="slow", timeout_seconds=2 if mode == "timeout" else 30)
            monkeypatch.setattr(cleaning_runtime, "_executor_command", lambda: blocking_execute_command(marker))
            task = asyncio.create_task(cleaning_runtime.process_assignment(bridge,
                {"job_id": identity, "shard_index": 0}, str(tmp_path)))
            try:
                await wait_entered(marker, task)
                process = children[-1]
                assert process.returncode is None
                if mode == "cancel":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(task, 4)
                else:
                    assert await asyncio.wait_for(task, 5) is False
                assert process.returncode is not None  # 실제 execute/내부 threads가 끝나고 wait/reap됨.
                shard = jobs.get_job(identity).shards[0]
                assert shard.status == "retry_wait" and shard.output_id is None
                assert all(not fields.get("output_id") for name, fields in bridge.reports if name == identity)
                print(json.dumps({"finding": "G2-F2", "mode": mode, "child_pid": process.pid,
                    "exit_code": process.returncode, "reaped": True, "state": shard.status}))
                monkeypatch.setattr(cleaning_runtime, "_executor_command", normal_command)
                fast = f"fast-after-{mode}"
                create(fast, timeout_seconds=10)
                assert await asyncio.wait_for(cleaning_runtime.process_assignment(bridge,
                    {"job_id": fast, "shard_index": 0}, str(tmp_path)), 5)
                assert jobs.get_job(fast).status == "completed"
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        assert all(p.returncode is not None for p in children)
        print(json.dumps({"finding": "G2-F2", "all_owned_child_pids": [p.pid for p in children],
                          "all_reaped": True, "followup_outputs": 2}))
    asyncio.run(scenario())


def test_G2_F1_new_due_job_uses_empty_slot_while_prior_recipe_waits(tmp_path, monkeypatch):
    entered, release, fast_done, slow_done = (threading.Event() for _ in range(4))
    children = capture_children(monkeypatch)
    create("slow", recipe_name="slow")
    class Dynamic(Bridge):
        def fetch_cleaning_recipe(self, name, version):
            if name == "slow":
                entered.set()
                assert release.wait(10)
            return super().fetch_cleaning_recipe(name, version)

        def report_cleaning_shard(self, identity, index, **fields):
            answer = super().report_cleaning_shard(identity, index, **fields)
            if not fields.get("error"):
                (fast_done if identity == "fast" else slow_done).set()
            return answer

    bridge = Dynamic()
    async def scenario():
        worker = asyncio.create_task(cleaning_runtime.run(bridge, str(tmp_path), poll_interval=0.02, concurrency=2))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            create("fast")  # 최초 목록에 없던 새 due 작업.
            assert await asyncio.to_thread(fast_done.wait, 5)
            assert not release.is_set()
            result = jobs.get_job("fast").shards[0]
            assert result.output_id and (tmp_path / ".cleaned" / result.output_id / "manifest.json").is_file()
            assert bridge.claims.count("fast") == bridge.claims.count("slow") == 1
            release.set()
            assert await asyncio.to_thread(slow_done.wait, 5)
        finally:
            release.set()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        assert all(p.returncode is not None for p in children)
    asyncio.run(scenario())


@pytest.mark.parametrize("reader", ["list", "get"])
def test_G2_F1_poll_read_and_progress_replace_do_not_overlap(reader, monkeypatch):
    create("j")
    token = jobs.start_shard("j", 0, "silo-1", "claim").shards[0].attempt_id
    entered, release, write_requested, write_attempt = (threading.Event() for _ in range(4))
    reading = threading.Event()
    reader_thread = []
    original_load, original_save = jobs.load_jobs, jobs.save_jobs

    def held_read():
        if reader_thread and threading.get_ident() == reader_thread[0]:
            # YAML parser가 파일을 열어 둔 실제 읽기 경계를 연장한다.
            from config.cleaning_manager import JOBS_FILE
            with JOBS_FILE.open(encoding="utf-8"):
                reading.set()
                entered.set()
                try:
                    assert release.wait(5)
                    return original_load()
                finally:
                    reading.clear()
        return original_load()

    def guarded_save(data):
        write_attempt.set()
        assert not reading.is_set(), "poll read handle overlaps atomic progress replacement"
        original_save(data)

    def snapshot():
        reader_thread.append(threading.get_ident())
        return jobs.list_jobs() if reader == "list" else jobs.get_job("j")

    def update():
        write_requested.set()
        return runtime.progress("j", 0, ShardProgress(silo_id="silo-1", attempt_id=token,
            processed_units=1, total_units=2, stage="test-progress"))

    monkeypatch.setattr(jobs, "load_jobs", held_read)
    monkeypatch.setattr(jobs, "save_jobs", guarded_save)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_read = pool.submit(snapshot)
        try:
            assert entered.wait(3)
            future_write = pool.submit(update)
            assert write_requested.wait(3)
            write_attempt.wait(0.2)  # writer가 lock에서 기다려도 reader를 유한 시간 안에 해제.
        finally:
            release.set()
        future_read.result(timeout=3)
        changed = future_write.result(timeout=3)
    assert changed.shards[0].processed_units == 1
    assert jobs.get_job("j").shards[0].processed_units == 1


def test_G2_F2_cli_sigterm_path_reaps_execution_child(tmp_path):
    create("signal", recipe_name="slow", timeout_seconds=30)
    job = jobs.start_shard("signal", 0, "silo-1", "signal-claim").model_dump()
    marker = tmp_path / "signal-execute-entered"
    payload = {"job": job, "recipe": recipes.get_recipe("slow", "1.0.0").model_dump(),
               "data_dir": str(tmp_path), "command": blocking_execute_command(marker)}
    code = "\n".join([
        "import asyncio, json, os, signal, sys, threading", "from pathlib import Path",
        "from silo_sdk import cleaning_runtime as runtime", "request = json.loads(sys.stdin.readline())",
        "created = []", "original = asyncio.create_subprocess_exec",
        "async def observed(*args, **kwargs):", "    process = await original(*args, **kwargs)",
        "    created.append(process)", "    try:",
        "        if directory := os.environ.get('FED_G2_PROCESS_ACK_DIR'):",
        "            for _ in range(1000):",
        "                if (Path(directory) / f'{process.pid}.seen').is_file(): break",
        "                await asyncio.sleep(0.01)",
        "            else: raise RuntimeError('missing sampling ack')",
        "        return process", "    except BaseException:",
        "        await runtime._stop_process(process)", "        raise",
        "asyncio.create_subprocess_exec = observed", "class Client:", "    silo_id = 'silo-1'",
        "    claimed = False", "    def list_assigned_shards(self, status):",
        "        return [] if self.claimed or status != 'pending' else [{'job_id': 'signal', 'shard_index': 0}]",
        "    def start_cleaning_shard(self, *args):", "        self.claimed = True",
        "        return request['job']", "    def fetch_cleaning_recipe(self, *args):",
        "        return request['recipe']", "    def cleaning_progress(self, *args): return {}",
        "    def report_cleaning_shard(self, *args, **fields):",
        "        print(json.dumps({'event': 'report', 'error': fields.get('error')}), flush=True)",
        "        return {}", "def control():",
        "    if sys.stdin.readline().strip() == 'STOP': signal.raise_signal(signal.SIGTERM)",
        "threading.Thread(target=control, daemon=True).start()",
        "runtime._executor_command = lambda: request['command']",
        "runtime.run_with_signals(Client(), request['data_dir'], poll_interval=0.02, concurrency=1)",
        "print(json.dumps({'child_pids': [p.pid for p in created], 'all_reaped': all(p.returncode is not None for p in created)}), flush=True)",
    ])
    worker = subprocess.Popen([sys.executable, "-u", "-c", code], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        worker.stdin.write(json.dumps(payload) + "\n")
        worker.stdin.flush()
        import time
        deadline = time.monotonic() + 6
        while not marker.is_file() and time.monotonic() < deadline and worker.poll() is None:
            time.sleep(0.01)
        assert marker.is_file(), "CLI의 실제 execute 진입 관측 필요"
        if os.name == "nt":
            worker.stdin.write("STOP\n")  # Windows 외부 os.kill은 TerminateProcess이므로 분리한다.
            worker.stdin.flush()
            signal_mode = "Python raised SIGTERM on Windows; Linux external SIGTERM remains D"
        else:
            worker.send_signal(signal.SIGTERM)
            signal_mode = "external POSIX SIGTERM"
        assert worker.wait(timeout=6) == 0
        messages = [json.loads(line) for line in worker.stdout.read().splitlines()]
        assert messages[-1]["all_reaped"] and len(messages[-1]["child_pids"]) == 1
        assert any(m.get("error") == "정제 worker 실행 취소" for m in messages)
        print(json.dumps({"finding": "G2-F2", "signal_mode": signal_mode, "worker_pid": worker.pid,
                          "worker_exit": worker.returncode, **messages[-1]}))
    finally:
        if worker.poll() is None:
            try:
                worker.stdin.write("STOP\n")
                worker.stdin.flush()
                worker.wait(timeout=4)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                worker.kill()
                worker.wait()
        worker.stdin.close()
        worker.stdout.close()
        worker.stderr.close()


@pytest.mark.parametrize("status,expected", [(404, "failed"), (429, "retry_wait"), (503, "retry_wait")])
def test_G2_F3_claimed_worker_classifies_recipe_http_failure(status, expected, tmp_path):
    create("pre", retry_backoff_seconds=0)
    create("post", depends_on=["pre"])
    class FailedRecipe(Bridge):
        def fetch_cleaning_recipe(self, name, version):
            raise SiloClientError(status, "sensitive response body must not be reported")
    bridge = FailedRecipe()
    assert asyncio.run(cleaning_runtime.process_assignment(bridge,
        {"job_id": "pre", "shard_index": 0}, str(tmp_path))) is False
    shard = jobs.get_job("pre").shards[0]
    assert shard.status == expected and shard.attempt == len(shard.attempts) == 1
    assert "sensitive" not in shard.error
    if expected == "failed":
        runtime.tick()
        assert jobs.get_job("post").status == "failed"
        assert len(jobs.get_job("pre").events) == len(jobs.get_job("post").events) == 1
    else:
        assert shard.next_attempt_at and not jobs.get_job("pre").events
        runtime.tick()
        assert asyncio.run(cleaning_runtime.process_assignment(Bridge(),
            {"job_id": "pre", "shard_index": 0}, str(tmp_path))) is True
        assert jobs.get_job("pre").shards[0].attempt == 2


@pytest.mark.parametrize("recovery", ["tick", "same_report"])
def test_G2_F4_interrupted_legacy_last_save_recovers_without_recleaning(recovery, tmp_path, monkeypatch):
    create("j")
    token = jobs.start_shard("j", 0, "silo-1", "claim").shards[0].attempt_id
    payload = ShardReport(job_id="j", shard_index=0, silo_id="silo-1", attempt_id=token,
        rows_in=10, rows_out=8, step_counters={"excluded": 2}, started_at="t", completed_at="t",
        schema_fingerprint="a" * 64, output_id="b" * 64, output_hash="c" * 64,
        source_hash="d" * 64, recipe_hash="e" * 64)
    original = jobs._save
    def interrupt(finalized):
        # 이전 두 단계 저장 중 첫 저장만 남은 중단 상태를 명시적으로 만든다.
        original(finalized.model_copy(update={"status": "pending", "total_rows_in": 0,
            "total_rows_out": 0, "aggregated_counters": {}}))
        raise OSError("last shard persisted; final publication interrupted")
    monkeypatch.setattr(jobs, "_save", interrupt)
    with pytest.raises(OSError):
        jobs.report_shard(payload)
    importlib.reload(jobs)
    assert jobs.get_job("j").status == "pending"
    if recovery == "tick":
        runtime.tick()
    else:
        jobs.report_shard(payload)
    final = jobs.get_job("j")
    assert final.status == "completed" and final.total_rows_in == 10 and final.total_rows_out == 8
    assert final.aggregated_counters == {"excluded": 2} and not final.events
    assert final.shards[0].output_id == "b" * 64 and final.shards[0].output_hash == "c" * 64
    runtime.tick()
    assert jobs.report_shard(payload).model_dump() == jobs.get_job("j").model_dump()
    from services import model_registry, training_round_service
    from models.packaging_schemas import ModelRegisterRequest
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"test-only")
    model_registry.register_model(ModelRegisterRequest(name="m", version="1.0.0",
        framework="pytorch", weights_path=str(weights)))
    round_entry = training_round_service.create_round(TrainingRoundCreate(model_name="m", version="1.0.0",
        group_id="g", cleaning_job_id="j", min_contributions=1))
    assert round_entry.cleaning_snapshot["silo-1"]["output_hash"] == "c" * 64


def test_G2_F4_last_report_publishes_shard_and_terminal_job_in_one_save(monkeypatch):
    create("j")
    shard = jobs.start_shard("j", 0, "silo-1", "claim").shards[0]
    calls = []
    original = jobs._save
    def observed(job):
        calls.append(job.model_dump())
        original(job)
    monkeypatch.setattr(jobs, "_save", observed)
    jobs.report_shard(ShardReport(job_id="j", shard_index=0, silo_id="silo-1", attempt_id=shard.attempt_id,
        rows_in=0, rows_out=0, started_at="t", completed_at="t", error="permanent"))
    assert len(calls) == 1 and calls[0]["status"] == "failed"
    assert calls[0]["shards"][0]["status"] == "failed" and len(calls[0]["events"]) == 1
    runtime.tick()
    assert len(jobs.get_job("j").events) == 1
