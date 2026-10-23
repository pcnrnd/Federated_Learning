"""진행 HTTP 지연/ACK 유실이 로컬 결과와 terminal 실행권한을 훼손하지 않는다."""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import threading
from datetime import timedelta

import pytest
from fastapi import HTTPException

from config.server_manager import save_servers
from models.cleaning_schemas import CleaningJobCreate, CleaningRecipeRequest, ShardProgress, ShardReport
from models.federated_schemas import SiloGroupRequest
from services import cleaning_execution as server, cleaning_job_service as jobs
from services import cleaning_recipe_service as recipes, silo_group_service as groups
from silo_sdk import cleaning_runtime as worker, synthetic
from silo_sdk.client import SiloClient, SiloClientError


def call(function, *args):
    try:
        return function(*args).model_dump()
    except HTTPException as exc:
        raise SiloClientError(exc.status_code, str(exc.detail)) from exc


class Bridge:
    def __init__(self, node="silo-1"):
        self.silo_id = node
        self.reports = []
        self.claims = []

    def list_assigned_shards(self, status):
        return [row.model_dump() for row in jobs.list_assigned_shards(self.silo_id, status)]

    def start_cleaning_shard(self, identity, index, claim):
        self.claims.append(identity)
        return call(jobs.start_shard, identity, index, self.silo_id, claim)

    def fetch_cleaning_recipe(self, name, version):
        return call(recipes.get_recipe, name, version)

    def get_cleaning_job(self, identity):
        return call(jobs.get_job, identity)

    def cleaning_progress(self, identity, index, token, done, total, stage):
        return call(server.progress, identity, index, ShardProgress(silo_id=self.silo_id,
            attempt_id=token, processed_units=done, total_units=total, stage=stage))

    def report_cleaning_shard(self, identity, index, **fields):
        self.reports.append(copy.deepcopy(fields))
        fields.setdefault("started_at", server.now().isoformat())
        fields.setdefault("completed_at", server.now().isoformat())
        return call(jobs.report_shard, ShardReport(job_id=identity, shard_index=index,
            silo_id=self.silo_id, **fields))


@pytest.fixture
def world(tmp_path):
    nodes = [f"silo-{i}" for i in range(1, 7)]
    save_servers({n: {"base_url": f"tcp://{n}:2375", "role": "client"} for n in nodes})
    groups.create_group(SiloGroupRequest(group_id="six", member_node_ids=nodes))
    recipes.register_recipe(CleaningRecipeRequest(name="r", version="1.0.0",
        steps=synthetic.HVC_STEPS, mapping=synthetic.HVC_MAPPING))
    for node in nodes:
        synthetic.write_sources(node, tmp_path / node)
    return nodes, tmp_path


def create(identity, **fields):
    return jobs.create_job(CleaningJobCreate(job_id=identity, recipe_name="r", recipe_version="1.0.0",
        group_id="six", dataset_label="silo-sources", timeout_seconds=20, **fields))


@pytest.mark.parametrize("mode", ["result", "timeout", "cancel"])
def test_blocked_progress_does_not_block_pipe_and_owned_child_is_reaped(mode, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    children, requests = [], []
    original = asyncio.create_subprocess_exec
    original_stop = worker._stop_process
    reaped = None

    async def observed(*args, **kwargs):
        process = await original(*args, **kwargs)
        children.append(process)
        return process

    async def observed_stop(process):
        await original_stop(process)
        reaped.set()

    class Slow:
        silo_id = "silo-1"

        def cleaning_progress(self, *args):
            requests.append(args)
            entered.set()
            assert release.wait(6)
            raise TimeoutError("ACK unknown; do not retry")

    code = "\n".join([
        "import json,sys,time", "json.load(sys.stdin)",
        "for i in range(3000):",
        " print(json.dumps(dict(type='progress',done=i,total=3000,stage='test')),flush=True)",
        " if i==0: time.sleep(.05)",
        "print(json.dumps(dict(type='result',manifest={'complete':True})),flush=True)"
        if mode == "result" else "time.sleep(3600)",
    ])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", observed)
    monkeypatch.setattr(worker, "_stop_process", observed_stop)
    monkeypatch.setattr(worker, "_executor_command", lambda: [sys.executable, "-u", "-c", code])

    async def scenario():
        nonlocal reaped
        reaped = asyncio.Event()
        task = asyncio.create_task(worker._execute(Slow(), {"job_id": "owned"},
            {"shard_index": 0, "attempt_id": "token"}, {}, "unused", .3 if mode == "timeout" else 10))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            if mode == "cancel":
                task.cancel()
            await asyncio.wait_for(reaped.wait(), 4)
            assert children[0].returncode is not None, "HTTP 대기 중에도 pipe 소비/child 종료·회수 필요"
            assert not task.done(), "실제 진행 HTTP thread 회수 전에는 실행 슬롯 반환 금지"
            assert len(requests) == 1, "진행 metadata 큐/HTTP thread를 무제한 생성하면 안 됨"
            release.set()
            if mode == "result":
                assert await task == {"complete": True}
            else:
                with pytest.raises(asyncio.TimeoutError if mode == "timeout" else asyncio.CancelledError):
                    await task
            assert len(requests) == 1  # pending 최신 값은 종료 시 폐기; unknown POST 재전송 없음.
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_progress_keeps_only_one_inflight_and_latest_snapshot():
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Slow:
        def cleaning_progress(self, *args):
            calls.append(args)
            if len(calls) == 1:
                entered.set()
                assert release.wait(3)

    async def scenario():
        sender = worker._Progress(Slow(), {"job_id": "j"}, {"shard_index": 0, "attempt_id": "t"})
        try:
            sender.publish(dict(done=0, total=1000, stage="start"))
            assert await asyncio.to_thread(entered.wait, 2)
            for done in range(1, 1001):
                sender.publish(dict(done=done, total=1000, stage="work"))
            assert len(calls) == 1
            release.set()
            for _ in range(100):
                if len(calls) == 2:
                    break
                await asyncio.sleep(.01)
            assert [row[3] for row in calls] == [0, 1000]
        finally:
            release.set()
            await sender.close()
        sender.publish(dict(done=1001, total=1001, stage="late"))
        assert len(calls) == 2
    asyncio.run(scenario())


def test_six_actual_executors_preserve_outputs_when_progress_ack_is_lost(world):
    nodes, path = world
    create("six-progress", max_attempts=1, partitions=4, parallelism=2)

    class LostProgress(Bridge):
        def cleaning_progress(self, *args):
            super().cleaning_progress(*args)
            raise TimeoutError("server may have committed; metadata best effort")

    clients = [LostProgress(node) for node in nodes]

    async def scenario():
        return await asyncio.gather(*(worker.process_assignment(client,
            {"job_id": "six-progress", "shard_index": index}, str(path / node))
            for index, (node, client) in enumerate(zip(nodes, clients))))
    assert asyncio.run(scenario()) == [True] * 6
    job = jobs.get_job("six-progress")
    assert job.status == "completed" and len(job.shards) == 6
    for node, shard, client in zip(nodes, job.shards, clients):
        assert shard.status == "completed" and shard.attempt == 1
        assert (path / node / ".cleaned" / shard.output_id / "manifest.json").is_file()
        assert len(client.reports) == 1 and not client.reports[0].get("error")


@pytest.mark.parametrize("outcome", ["committed", "uncommitted", "read-failed", "wrong-token", "failed", "invalid-ack", "malformed-ack"])
def test_terminal_ack_reconciles_exact_state_without_opposite_write_or_replay(world, outcome):
    nodes, path = world
    create("ack", max_attempts=1)

    class Ack(Bridge):
        reads = 0

        def report_cleaning_shard(self, identity, index, **fields):
            if outcome == "committed":
                super().report_cleaning_shard(identity, index, **fields)
            else:
                self.reports.append(copy.deepcopy(fields))
            if outcome == "invalid-ack":
                ack = super().get_cleaning_job(identity)
                ack["shards"][0].update(status="completed", attempt_id="not-this-token")
                return ack
            if outcome == "malformed-ack":
                return {"shards": None}
            raise TimeoutError("terminal POST ACK unknown")

        def get_cleaning_job(self, identity):
            self.reads += 1
            if outcome == "read-failed":
                raise TimeoutError("GET also unavailable")
            current = super().get_cleaning_job(identity)
            if outcome == "wrong-token":
                current["shards"][0].update(status="completed", attempt_id="f" * 32)
            elif outcome == "failed":
                current["shards"][0]["status"] = "failed"
            return current

    client = Ack(nodes[0])
    action = worker.process_assignment(client, {"job_id": "ack", "shard_index": 0}, str(path / nodes[0]))
    if outcome in {"uncommitted", "read-failed", "invalid-ack", "malformed-ack"}:
        with pytest.raises(worker.TerminalAckUnknown):
            asyncio.run(action)
    else:
        assert asyncio.run(action) is (outcome == "committed")
    assert client.reads == len(client.reports) == 1
    assert not client.reports[0].get("error")
    assert list((path / nodes[0] / ".cleaned").glob("*/manifest.json"))
    if outcome in {"uncommitted", "read-failed", "invalid-ack", "malformed-ack"}:
        # 새 worker의 pending 조회에도 미종결 running attempt는 노출되지 않는다.
        assert jobs.get_job("ack").shards[0].status == "running"
        assert jobs.list_assigned_shards(nodes[0], "pending") == []


def test_deadline_retry_closes_token_before_new_claim_and_rejects_late_progress(world):
    nodes, _ = world
    create("late", max_attempts=2, retry_backoff_seconds=0)
    client = Bridge(nodes[0])
    first = client.start_cleaning_shard("late", 0, "old")
    old = first["shards"][0]
    job = jobs.get_job("late")
    server.save_shard(job, 0, job.shards[0].model_copy(update={
        "deadline_at": (server.now() - timedelta(seconds=1)).isoformat()}))
    server.tick()
    server.tick()
    second = client.start_cleaning_shard("late", 0, "new")
    assert second["shards"][0]["attempt_id"] != old["attempt_id"]
    with pytest.raises(SiloClientError) as stale:
        client.cleaning_progress("late", 0, old["attempt_id"], 1, 1, "late")
    assert stale.value.status == 409
    with pytest.raises(SiloClientError):
        client.report_cleaning_shard("late", 0, rows_in=0, rows_out=0,
            step_counters={}, attempt_id=old["attempt_id"], error="old report")
    assert jobs.get_job("late").shards[0].attempt_id == second["shards"][0]["attempt_id"]


def test_respawn_holds_all_new_claims_until_orphan_running_attempt_is_closed(world):
    nodes, path = world
    create("orphan", max_attempts=1)
    old = Bridge(nodes[0])
    claimed = old.start_cleaning_shard("orphan", 0, "old-process")
    create("next", max_attempts=1)
    fresh = Bridge(nodes[0])
    asyncio.run(worker.run(fresh, str(path / nodes[0]), poll_interval=.01, max_cycles=1))
    assert fresh.claims == []  # 다른 pending job도 admission 금지.
    old.report_cleaning_shard("orphan", 0, rows_in=0, rows_out=0, step_counters={},
        attempt_id=claimed["shards"][0]["attempt_id"], error="known terminal closure")
    asyncio.run(worker.run(fresh, str(path / nodes[0]), poll_interval=.01, max_cycles=1))
    assert fresh.claims == ["next"]
    assert jobs.get_job("next").shards[0].status == "completed"


@pytest.mark.parametrize("response", [None, {}, ["wrong"], [{}],
    [{"job_id": "j", "shard_index": 0, "generation": 0, "silo_id": "silo-1", "status": "pending"}]])
def test_malformed_running_list_is_hold(response):
    class Malformed:
        silo_id = "silo-1"

        def list_assigned_shards(self, status):
            assert status == "running"
            return response
    assert asyncio.run(worker._admission_ready(Malformed(), {})) is False


@pytest.mark.parametrize("response", [None, {}, "bad", []])
def test_sdk_assigned_list_preserves_empty_success_and_rejects_nonlist(response, monkeypatch):
    client = SiloClient("http://unused", "silo-1", timeout=2, retries=0)
    monkeypatch.setattr(client, "_request", lambda *args: response)
    if response == []:
        assert client.list_assigned_shards("running") == []
        assert asyncio.run(worker._admission_ready(client, {})) is True
    else:
        with pytest.raises(SiloClientError) as error:
            client.list_assigned_shards("running")
        assert error.value.status == 502
        assert asyncio.run(worker._admission_ready(client, {})) is False


@pytest.mark.parametrize("boundary", ["claim", "recipe"])
def test_preexecutor_timeout_remains_distinct_and_never_claims_compute_success(world, boundary):
    nodes, path = world
    create("pre", max_attempts=1)

    class Pre(Bridge):
        def start_cleaning_shard(self, *args):
            job = super().start_cleaning_shard(*args)
            if boundary == "claim":
                raise TimeoutError("claim may be committed")
            return job

        def fetch_cleaning_recipe(self, *args):
            raise TimeoutError("recipe read unavailable")

    client = Pre(nodes[0])
    # 재전송 예산 0: claim 확인을 포기한 경계(재전송 회수는 test_cleaning_claim_latency).
    action = worker.process_assignment(client, {"job_id": "pre", "shard_index": 0, "timeout_seconds": 0},
                                       str(path / nodes[0]))
    if boundary == "claim":
        with pytest.raises(TimeoutError):
            asyncio.run(action)
        assert client.reports == []
        assert asyncio.run(worker._admission_ready(Bridge(nodes[0]), {})) is False
    else:
        assert asyncio.run(action) is False
        assert len(client.reports) == 1 and client.reports[0]["error"].endswith("TimeoutError")
    assert not list((path / nodes[0]).glob(".cleaned/*/manifest.json"))


def test_cancellation_during_terminal_post_reaps_io_without_opposite_failure(world):
    nodes, path = world
    create("cancel-report", max_attempts=1)
    entered, release = threading.Event(), threading.Event()

    class SlowReport(Bridge):
        def report_cleaning_shard(self, *args, **fields):
            entered.set()
            assert release.wait(3)
            return super().report_cleaning_shard(*args, **fields)

    client = SlowReport(nodes[0])

    async def scenario():
        task = asyncio.create_task(worker.process_assignment(client,
            {"job_id": "cancel-report", "shard_index": 0}, str(path / nodes[0])))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.sleep(.02)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
    assert len(client.reports) == 1 and not client.reports[0].get("error")
    assert jobs.get_job("cancel-report").shards[0].status == "completed"


@pytest.mark.parametrize("raw", [b"{broken", b"\xff"])
@pytest.mark.parametrize("boundary", ["progress", "terminal"])
def test_real_sdk_raw_response_decode_errors_preserve_success_output(world, monkeypatch, raw, boundary):
    nodes, path = world
    create("decode", max_attempts=1)
    decoded_requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            decoded_requests.append(raw)
            return raw

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    sdk = SiloClient("http://unused", nodes[0], timeout=2, retries=0)

    class Decode(Bridge):
        def cleaning_progress(self, *args):
            if boundary == "progress":
                return sdk.cleaning_progress(*args)
            return super().cleaning_progress(*args)

        def report_cleaning_shard(self, *args, **fields):
            answer = super().report_cleaning_shard(*args, **fields)
            if boundary == "terminal":
                return sdk.report_cleaning_shard(*args, **fields)
            return answer

    # 실제 executor의 첫 progress 뒤에 짧게 양보해 HTTP raw-body decoder 실행을 보장한다.
    code = "\n".join([
        "import time", "from silo_sdk import cleaning_executor as executor",
        "original = executor.send", "def send(message):", " original(message)",
        " if message['type']=='progress': time.sleep(.05)", "executor.send=send",
        "raise SystemExit(executor.main())",
    ])
    monkeypatch.setattr(worker, "_executor_command", lambda: [sys.executable, "-u", "-c", code])
    client = Decode(nodes[0])
    assert asyncio.run(worker.process_assignment(client,
        {"job_id": "decode", "shard_index": 0}, str(path / nodes[0]))) is True
    assert decoded_requests and len(client.reports) == 1 and not client.reports[0].get("error")
    shard = jobs.get_job("decode").shards[0]
    assert shard.status == "completed" and (path / nodes[0] / ".cleaned" / shard.output_id / "manifest.json").is_file()


@pytest.mark.parametrize("change", ["generation-missing", "generation-null", "generation-bool",
    "generation-string", "generation-old", "token-missing", "token-null", "token-malformed", "index-bool",
    "status-list", "status-dict"])
def test_malformed_get_is_unknown_not_a_fence_and_blocks_queued_cycle_work(world, change):
    nodes, path = world
    create("ambiguous", max_attempts=1)
    create("queued", max_attempts=1)

    class MalformedGet(Bridge):
        def report_cleaning_shard(self, identity, index, **fields):
            self.reports.append(copy.deepcopy(fields))
            raise TimeoutError("terminal ACK unknown")

        def get_cleaning_job(self, identity):
            value = super().get_cleaning_job(identity)
            if change == "generation-missing":
                value.pop("generation")
            elif change.startswith("generation-"):
                value["generation"] = {"null": None, "bool": False, "string": "0", "old": -1}[change.split('-')[1]]
            elif change == "token-missing":
                value["shards"][0].pop("attempt_id")
            elif change == "index-bool":
                value["shards"][0]["shard_index"] = False
            elif change.startswith("status-"):
                value["shards"][0]["status"] = [] if change == "status-list" else {}
            else:
                value["shards"][0]["attempt_id"] = None if change == "token-null" else "invalid"
            return value

    client = MalformedGet(nodes[0])
    with pytest.raises(worker.TerminalAckUnknown):
        asyncio.run(worker.cycle(client, str(path / nodes[0]), concurrency=1))
    assert client.claims == ["ambiguous"]
    assert len(client.reports) == 1 and not client.reports[0].get("error")


@pytest.mark.parametrize("raw", [b"{", b"\xff"])
def test_raw_running_list_decode_failure_is_hold(monkeypatch, raw):
    client = SiloClient("http://unused", "silo-1", timeout=2, retries=0)

    def decode(*args):
        return json.loads(raw.decode("utf-8"))

    monkeypatch.setattr(client, "_request", decode)
    assert asyncio.run(worker._admission_ready(client, {})) is False
