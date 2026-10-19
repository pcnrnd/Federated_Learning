"""G2 실행권한·영속 예약·DAG·실제 로컬 출력·비동기/분할 의미 회귀."""
from __future__ import annotations

import argparse
import asyncio
import importlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from config.server_manager import save_servers
from models.cleaning_schemas import CleaningJobCreate, CleaningRecipeRequest, ShardReport, ShardProgress
from models.federated_schemas import SiloGroupRequest
from services import cleaning_execution as runtime, cleaning_job_service as jobs
from services import cleaning_recipe_service as recipes, silo_group_service
from silo_sdk import synthetic
from silo_sdk.cleaning import apply_recipe
from silo_sdk import cleaning_output, cleaning_runtime


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    clock = [datetime(2026, 10, 19, tzinfo=timezone.utc)]
    monkeypatch.setattr(runtime, "now", lambda: clock[0])
    save_servers({"silo-1": {"base_url": "tcp://silo-1:2375", "role": "client"}})
    silo_group_service.create_group(SiloGroupRequest(group_id="g", member_node_ids=["silo-1"]))
    for name in ("r", "slow"):
        recipes.register_recipe(CleaningRecipeRequest(name=name, version="1.0.0",
            steps=synthetic.HVC_STEPS, mapping=synthetic.HVC_MAPPING))
    return clock


def create(identity="j", **extra):
    return jobs.create_job(CleaningJobCreate(job_id=identity, recipe_name="r", recipe_version="1.0.0",
        group_id="g", dataset_label="silo-sources", **extra))


def claim(identity="j", key="claim"):
    return jobs.start_shard(identity, 0, "silo-1", key).shards[0]


def result(identity, token, **extra):
    return ShardReport(job_id=identity, shard_index=0, silo_id="silo-1", attempt_id=token,
        rows_in=10, rows_out=8, step_counters={"excluded": 2}, started_at="2026-10-19T00:00:00Z",
        completed_at="2026-10-19T00:00:01Z", schema_fingerprint="a" * 64,
        output_id="b" * 64, output_hash="c" * 64, source_hash="d" * 64, recipe_hash="e" * 64, **extra)


def test_due_claim_is_unique_and_survives_reload(setup):
    create(scheduled_at=(setup[0] + timedelta(seconds=10)).isoformat())
    assert jobs.list_assigned_shards("silo-1", "pending") == []
    with pytest.raises(HTTPException):
        claim()
    setup[0] += timedelta(seconds=10)
    with ThreadPoolExecutor(max_workers=2) as pool:
        def attempt(key):
            try:
                return claim(key=key).attempt_id
            except HTTPException as exc:
                return exc.status_code
        tokens = list(pool.map(attempt, ["one", "two"]))
    assert tokens.count(409) == 1
    stored = jobs.get_job("j").shards[0]
    assert claim(key=stored.claim_id).attempt_id == stored.attempt_id
    importlib.reload(jobs)
    assert jobs.get_job("j").shards[0].attempt_id == stored.attempt_id
    assert jobs.list_assigned_shards("silo-1", "pending") == []


def test_retry_idempotency_and_late_attempt_do_not_duplicate_output(setup):
    create(retry_backoff_seconds=5)
    first = claim()
    jobs.report_shard(result("j", first.attempt_id, error="transient", retryable=True))
    assert jobs.get_job("j").shards[0].status == "retry_wait"
    with pytest.raises(HTTPException):
        claim()
    setup[0] += timedelta(seconds=5)
    runtime.tick()
    second = claim(key="two")
    good = result("j", second.attempt_id)
    assert jobs.report_shard(good).total_rows_out == 8
    assert jobs.report_shard(good).total_rows_out == 8
    with pytest.raises(HTTPException):
        jobs.report_shard(result("j", first.attempt_id))
    assert jobs.get_job("j").shards[0].attempt == 2
    assert [a["status"] for a in jobs.get_job("j").shards[0].attempts] == ["failed", "completed"]


def test_timeout_exhaustion_reschedule_and_progress_revoke_old_execution(setup):
    create(timeout_seconds=2, max_attempts=1)
    first = claim()
    runtime.progress("j", 0, ShardProgress(silo_id="silo-1", attempt_id=first.attempt_id,
                                        processed_units=1, total_units=6, stage="map_schema"))
    with pytest.raises(HTTPException):
        runtime.progress("j", 0, ShardProgress(silo_id="silo-1", attempt_id=first.attempt_id,
                                            processed_units=0, total_units=6))
    setup[0] += timedelta(seconds=3)
    with pytest.raises(HTTPException):
        claim()  # 같은 claim 재전송도 deadline 뒤에는 실행권한을 돌려주지 않는다.
    runtime.tick()
    runtime.tick()
    failed = jobs.get_job("j")
    assert failed.status == "failed" and len(failed.events) == 1
    assert failed.shards[0].error == "정제 실행 시간초과"
    scheduled = setup[0] + timedelta(seconds=5)
    runtime.reschedule("j", scheduled.isoformat())
    importlib.reload(jobs)
    assert jobs.get_job("j").generation == 1
    with pytest.raises(HTTPException):
        jobs.report_shard(result("j", first.attempt_id))
    setup[0] = scheduled
    second = claim(key="second-generation")
    jobs.report_shard(result("j", second.attempt_id))
    assert jobs.get_job("j").status == "completed"
    with pytest.raises(HTTPException):
        jobs.report_shard(result("j", first.attempt_id))


def test_dag_executes_after_success_and_propagates_final_failure():
    create("pre")
    create("post", depends_on=["pre"])
    with pytest.raises(HTTPException):
        claim("post")
    with pytest.raises(HTTPException):
        runtime.require_training_output("pre")
    pre = claim("pre")
    jobs.report_shard(result("pre", pre.attempt_id))
    assert claim("post").status == "running"
    assert runtime.require_training_output("pre").status == "completed"
    create("bad")
    create("blocked", depends_on=["bad"])
    token = claim("bad").attempt_id
    jobs.report_shard(result("bad", token, error="permanent"))
    runtime.tick()
    assert jobs.get_job("blocked").status == "failed"
    assert len(jobs.get_job("blocked").events) == 1
    for identity, deps in (("self", ["self"]), ("unknown", ["absent"])):
        with pytest.raises(HTTPException):
            create(identity, depends_on=deps)


def test_periodic_occurrence_is_persisted_once_and_previous_result_immutable(setup):
    create(interval_seconds=10, max_occurrences=2, scheduled_at=setup[0].isoformat())
    token = claim().attempt_id
    jobs.report_shard(result("j", token))
    runtime.tick()
    assert len(jobs.list_jobs()) == 1
    setup[0] += timedelta(seconds=10)
    runtime.tick()
    importlib.reload(jobs)
    runtime.tick()
    assert len(jobs.list_jobs()) == 2
    next_job = next(j for j in jobs.list_jobs() if j.job_id != "j")
    assert next_job.occurrence == 2 and next_job.schedule_id == "j"
    assert jobs.get_job("j").shards[0].output_hash == "c" * 64
    jobs.report_shard(result(next_job.job_id, claim(next_job.job_id).attempt_id))
    setup[0] += timedelta(seconds=100)
    runtime.tick()
    assert len(jobs.list_jobs()) == 2


@pytest.mark.parametrize("silo", [f"silo-{i}" for i in range(1, 7)])
def test_hvc_partitioned_output_and_counters_match_serial_without_source_mutation(silo):
    original = synthetic.generate_sources(silo)
    import copy
    before = copy.deepcopy(original)
    steps = [*synthetic.HVC_STEPS, {"type": "normalize", "params": {"column": "x1"}},
             {"type": "dedupe", "params": {"keys": ["id"]}}]
    assert apply_recipe(original, steps, mapping=synthetic.HVC_MAPPING, partitions=7, parallelism=2) == apply_recipe(original, steps, mapping=synthetic.HVC_MAPPING)
    assert original == before


def test_snapshot_is_used_after_source_change_and_partial_fixture_does_not_overwrite(tmp_path):
    paths = synthetic.write_sources("silo-1", tmp_path)
    create()
    shard = claim()
    job = jobs.get_job("j").model_dump()
    recipe = recipes.get_recipe("r", "1.0.0").model_dump()
    manifest = cleaning_output.execute(str(tmp_path), "silo-1", job, shard.model_dump(), recipe)
    before, _ = cleaning_output.load_output(str(tmp_path), manifest)
    paths["period_a"].write_text("modified source", encoding="utf-8")
    assert cleaning_output.execute(str(tmp_path), "silo-1", job, shard.model_dump(), recipe) == manifest
    assert cleaning_output.load_output(str(tmp_path), manifest)[0] == before
    paths["entity"].unlink()
    with pytest.raises(FileNotFoundError):
        synthetic.ensure_sources("silo-1", tmp_path)
    assert paths["period_a"].read_text() == "modified source"
    location = cleaning_output.output_path(str(tmp_path), manifest["output_id"])
    (location / "recipe.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="recipe hash"):
        cleaning_output.load_output(str(tmp_path), manifest)


@pytest.mark.parametrize("count", [0, 1, 7])
def test_empty_single_uneven_partitions_preserve_row_order_counts_and_global_statistics(count):
    rows = [{"id": i // 2, "x": str(i), "name": " A "} for i in range(count)]
    steps = [{"type": "trim_whitespace", "params": {"columns": ["name"]}},
        {"type": "cast", "params": {"column": "x", "to": "float"}},
        {"type": "normalize", "params": {"column": "x"}},
        {"type": "dedupe", "params": {"keys": ["id"]}}]
    assert apply_recipe(rows, steps, partitions=4, parallelism=2) == apply_recipe(rows, steps)


def test_internal_partition_work_overlaps_and_respects_parallelism(monkeypatch):
    import silo_sdk.cleaning as cleaning
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    active, peak, calls = 0, 0, 0
    original = cleaning._SINGLE_TABLE_STEPS["lowercase"]

    def observed(rows, params):
        nonlocal active, peak, calls
        with lock:
            active += 1
            peak = max(peak, active)
            calls += 1
            index = calls
        if index <= 2:
            barrier.wait(timeout=3)  # 두 구간이 동시에 실제 함수 안에 들어와야 통과
        try:
            return original(rows, params)
        finally:
            with lock:
                active -= 1

    monkeypatch.setitem(cleaning._SINGLE_TABLE_STEPS, "lowercase", observed)
    rows, counts = cleaning.apply_recipe([{"name": "A"} for _ in range(7)],
        [{"type": "lowercase", "params": {"columns": ["name"]}}], partitions=4, parallelism=2)
    assert peak == 2 and calls == 4
    assert rows == [{"name": "a"} for _ in range(7)] and counts == {"lowercase": 7}


def test_real_async_worker_finishes_independent_job_while_one_recipe_io_waits(tmp_path):
    synthetic.write_sources("silo-1", tmp_path)
    create("fast")
    jobs.create_job(CleaningJobCreate(job_id="slow", recipe_name="slow", recipe_version="1.0.0",
                                    group_id="g", dataset_label="silo-sources"))
    fast_done = threading.Event()
    observations, payloads = [], []

    class Bridge:
        silo_id = "silo-1"

        def list_assigned_shards(self, status):
            return sorted([a.model_dump() for a in jobs.list_assigned_shards(self.silo_id, status)],
                          key=lambda a: a["job_id"], reverse=True)  # slow를 먼저 요청

        def start_cleaning_shard(self, job_id, index, claim_id):
            return jobs.start_shard(job_id, index, self.silo_id, claim_id).model_dump()

        def fetch_cleaning_recipe(self, name, version):
            if name == "slow":
                observations.append("slow_wait")
                assert fast_done.wait(5), "독립 fast 작업이 느린 recipe I/O 동안 전진해야 함"
                observations.append("slow_resumed")
            return recipes.get_recipe(name, version).model_dump()

        def cleaning_progress(self, job_id, index, attempt_id, done, total, stage):
            return runtime.progress(job_id, index, ShardProgress(silo_id=self.silo_id,
                attempt_id=attempt_id, processed_units=done, total_units=total, stage=stage)).model_dump()

        def report_cleaning_shard(self, job_id, index, **fields):
            payloads.append(fields)
            fields.setdefault("started_at", "2026-10-19T00:00:00Z")
            fields.setdefault("completed_at", "2026-10-19T00:00:01Z")
            answer = jobs.report_shard(ShardReport(job_id=job_id, shard_index=index,
                silo_id=self.silo_id, **fields)).model_dump()
            if job_id == "fast":
                observations.append("fast_done")
                fast_done.set()
            return answer

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert asyncio.run(cleaning_runtime.cycle(Bridge(), str(tmp_path), executor)) == [True, True]
    assert observations.index("slow_wait") < observations.index("fast_done") < observations.index("slow_resumed")
    assert all(j.status == "completed" for j in jobs.list_jobs())
    assert all("rows" not in p and "source_files" not in p for p in payloads)
    from scripts.silo_worker import _linked_output
    args = argparse.Namespace(silo_id="silo-1", data_dir=str(tmp_path))
    bridge = Bridge()
    bridge.get_cleaning_job = lambda identity: jobs.get_job(identity).model_dump()
    rows, stats = _linked_output(args, bridge, "fast")
    assert len(rows) == jobs.get_job("fast").shards[0].rows_out == stats["rows_after_cleaning"]
    frozen = jobs.get_job("fast").shards[0].model_dump()
    runtime.reschedule("fast", "2099-01-01T00:00:00+00:00")
    bridge.get_cleaning_job = lambda _identity: pytest.fail("진행 라운드는 현재 정제 job 재조회 금지")
    assert _linked_output(args, bridge, "fast", {"silo-1": frozen})[0] == rows


def test_api_claim_report_idempotency_and_reschedule_validate_execution_identity(monkeypatch):
    from fastapi.testclient import TestClient
    from config import settings
    from main import app
    monkeypatch.setattr(settings, "API_KEY", "")
    create()
    client = TestClient(app)
    path = "/api/cleaning-jobs/j/shards/0"
    claim_body = {"silo_id": "silo-1", "claim_id": "same-request"}
    first = client.post(f"{path}/start", json=claim_body).json()
    again = client.post(f"{path}/start", json=claim_body).json()
    assert first["shards"][0]["attempt_id"] == again["shards"][0]["attempt_id"]
    payload = result("j", first["shards"][0]["attempt_id"]).model_dump()
    assert client.post(f"{path}/report", json=payload).json()["total_rows_out"] == 8
    assert client.post(f"{path}/report", json=payload).json()["total_rows_out"] == 8
    assert client.post(f"{path}/report", json={**payload, "attempt_id": "wrong"}).status_code == 409
    assert client.post("/api/cleaning-jobs/j/reschedule", json={"scheduled_at": "2026-10-19T00:00:00"}).status_code == 422
    assert client.post("/api/cleaning-jobs/j/shards/-1/start", json=claim_body).status_code == 400


def test_async_cancellation_revokes_attempt_and_cleans_progress_task(tmp_path):
    create()
    entered, release = threading.Event(), threading.Event()
    class Client:
        silo_id = "silo-1"

        def start_cleaning_shard(self, identity, index, claim_id):
            return jobs.start_shard(identity, index, self.silo_id, claim_id).model_dump()

        def fetch_cleaning_recipe(self, name, version):
            entered.set()
            assert release.wait(5)
            return recipes.get_recipe(name, version).model_dump()

        def report_cleaning_shard(self, identity, index, **fields):
            return jobs.report_shard(ShardReport(job_id=identity, shard_index=index,
                silo_id=self.silo_id, started_at="t", completed_at="t", **fields)).model_dump()

    async def scenario(executor):
        task = asyncio.create_task(cleaning_runtime.process_assignment(Client(),
            {"job_id": "j", "shard_index": 0}, str(tmp_path), executor))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        asyncio.run(scenario(executor))
    shard = jobs.get_job("j").shards[0]
    assert shard.status == "retry_wait" and shard.error == "정제 worker 실행 취소"
    assert shard.output_id is None
