"""실제 로컬 정제→카운트→durable ACK/중앙 원장. 원시 행은 사일로 안에만 둔다."""
from __future__ import annotations

import asyncio
import copy
import csv
import importlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from config import settings
from config.server_manager import save_servers
from main import app
from models.cleaning_schemas import CleaningJobCreate, CleaningRecipeRequest, ShardReport
from models.federated_schemas import SiloGroupRequest
from models.monitoring_schemas import BaselineRequest
from models.packaging_schemas import ModelRegisterRequest
from services import cleaning_job_service as jobs, cleaning_recipe_service as recipes
from services import distribution_service as service, drift_detector, model_registry, silo_group_service
from silo_sdk import cleaning_runtime
from silo_sdk import distribution_runtime
from silo_sdk.cleaning_output import execute, load_output
from silo_sdk.client import SiloClient, SiloClientError
from silo_sdk.distribution_runtime import DistributionCollector
from silo_sdk.distributions import build_report, edges, histogram, sha
from silo_sdk.iterative_ridge import train_iterative_ridge
from storage.factory import reset_repositories

PRIVATE = "secret-row-value-not-central"


@pytest.fixture(params=["yaml", "sqlite"])
def world(request, monkeypatch, tmp_path):
    monkeypatch.setenv("FED_STORAGE", request.param)
    reset_repositories()
    save_servers({node: {"base_url": f"tcp://{node}:2375", "role": "client"}
                  for node in ("silo-1", "silo-2")})
    silo_group_service.create_group(SiloGroupRequest(group_id="g", member_node_ids=["silo-1"]))
    model_registry.register_model(ModelRegisterRequest(name="m", version="1.0.0", framework="pytorch",
        weights_path="unused-unit-fixture.pt", input_schema={"features": ["x"]}, output_schema={"target": "y"}))
    recipe = recipes.register_recipe(CleaningRecipeRequest(name="r", version="1.0.0", steps=[
        {"type": "trim_whitespace", "params": {"columns": ["x"]}},
        {"type": "dedupe", "params": {"keys": ["id"]}},
    ]))
    return {"data": tmp_path / "silo-local", "recipe": recipe.model_dump(mode="json"), "mode": request.param}


def output(world, identity="job-1", *, suffix="json", values=None,
           completed_at="2026-10-20T00:01:30+00:00"):
    directory = world["data"]
    directory.mkdir(exist_ok=True)
    if values is None:
        values = [" -3 ", "0", "1", "10", "11", "30", "", "NaN", "Inf", "True", PRIVATE]
    rows = [{"id": f"{PRIVATE}-{n}", "x": value, "y": "987654.321098765"} for n, value in enumerate(values)]
    raw = [*rows, *rows[:1]]  # 실제 dedupe가 한 행을 제거한다.
    path = directory / f"input.{suffix}"
    if suffix == "csv":
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["id", "x", "y"])
            writer.writeheader()
            writer.writerows(raw)
    else:
        path.write_text(json.dumps(raw), encoding="utf-8")
    jobs.create_job(CleaningJobCreate(job_id=identity, recipe_name="r", recipe_version="1.0.0",
                                     group_id="g", dataset_label="input"))
    job = jobs.start_shard(identity, 0, "silo-1", identity).model_dump()
    shard = job["shards"][0]
    manifest = execute(str(directory), "silo-1", job, shard, world["recipe"])
    fields = {key: manifest[key] for key in ("rows_in", "rows_out", "step_counters", "schema_fingerprint",
                                            "output_id", "output_hash", "source_hash", "recipe_hash")}
    done = jobs.report_shard(ShardReport(job_id=identity, shard_index=0, silo_id="silo-1", **fields,
        attempt_id=shard["attempt_id"], started_at=shard["started_at"], completed_at=completed_at))
    path.unlink()  # 성공 출력만 소비해야 한다. 이후 원천 부재가 재정제/fallback을 유발하면 실패한다.
    return manifest, done.model_dump()["shards"][0]


def config_for(world, manifest, **changes):
    definition = {"model_name": "m", "version": "1.0.0", "node_ids": ["silo-1"], "feature": "x",
        "feature_columns": ["x"],
        "bin_edges": [0, 10, 20], "schema_fingerprint": manifest["schema_fingerprint"],
        "recipe_name": "r", "recipe_version": "1.0.0", "recipe_hash": sha(world["recipe"]),
        "target_column": "y", "entity_id_columns": ["id"], "window_seconds": 60}
    definition.update(changes)
    return service.create_config(definition)


def report_for(world, manifest, shard, config):
    rows, stored = load_output(str(world["data"]), manifest)
    return build_report(rows, stored, config, shard)


class Bridge:
    silo_id = "silo-1"

    def __init__(self, *, lose_ack=False):
        self.calls = []
        self.lose_ack = lose_ack

    def list_distribution_configs(self):
        return service.list_configs(self.silo_id)

    def list_assigned_shards(self, status="pending"):
        return [a.model_dump() for a in jobs.list_assigned_shards(self.silo_id, status)]

    def get_cleaning_job(self, job_id):
        return jobs.get_job(job_id).model_dump()

    def push_distribution_report(self, report):
        self.calls.append(copy.deepcopy(report))
        try:
            ack = service.accept_report(report)
        except HTTPException as exc:
            raise SiloClientError(exc.status_code, "분포 보고 거부") from exc
        if self.lose_ack:
            self.lose_ack = False
            raise OSError("ACK 유실")
        return ack


@pytest.mark.parametrize("suffix", ["csv", "json"])
def test_actual_cleaned_output_counts_conservation_and_privacy(world, suffix):
    manifest, shard = output(world, suffix=suffix)
    config = config_for(world, manifest)
    client = Bridge()
    DistributionCollector(client, str(world["data"])).cycle()
    report = service.get_current(config["config_id"], "silo-1")
    # [-3,0,1]와 [10,11,30] 각 3개. 범위 밖 clip과 왼쪽 경계를 손으로 대조.
    assert report["bin_counts"] == [3, 3]
    assert (report["total_count"], report["valid_count"], report["excluded_count"]) == (11, 6, 5)
    assert manifest["rows_in"] == 12 and manifest["rows_out"] == 11
    assert report["output_id"] == manifest["output_id"] and report["attempt_id"] == shard["attempt_id"]
    assert report["window_start"] == "2026-10-20T00:01:00+00:00"
    assert report["window_end"] == "2026-10-20T00:02:00+00:00"
    assert PRIVATE not in json.dumps(client.calls)
    assert "987654.321098765" not in json.dumps(client.calls)
    for path in settings.CONFIG_DIR.glob("*.yaml"):
        assert PRIVATE not in path.read_text(encoding="utf-8")
    assert PRIVATE not in json.dumps(service._load())  # SQLite JSON을 포함한 중앙 원장 검사.


def test_counts_use_the_same_joint_training_row_filter_without_exposing_target():
    rows = [{"x": 1, "other": 2, "y": 3}, {"x": 11, "other": 3, "y": 4},
            {"x": 5, "other": None, "y": 10}, {"x": 6, "other": 7, "y": True},
            {"x": 7, "other": "NaN", "y": 9}, {"x": float("inf"), "other": 1, "y": 8}]
    stats = histogram(rows, "x", [0, 10, 20], feature_columns=["x", "other"], target_column="y")
    trained = train_iterative_ridge(rows, ["x", "other"], "y", initial_parameters=[0, 0, 0],
                                    l2=0, step_size=0.001, steps=1)
    assert stats == {"bin_counts": [1, 1], "total_count": 6, "valid_count": 2, "excluded_count": 4}
    assert (stats["valid_count"], stats["excluded_count"]) == (trained.sample_count, trained.rows_excluded)


def test_ack_loss_reload_and_repeated_poll_use_exact_durable_payload(world):
    manifest, _ = output(world)
    config = config_for(world, manifest)
    client = Bridge(lose_ack=True)
    first = DistributionCollector(client, str(world["data"]))
    first.cycle()
    journal = next(first.directory.glob("*.json"))
    assert json.loads(journal.read_bytes())["status"] == "pending"
    first_report = service.get_current(config["config_id"], "silo-1")
    reset_repositories()
    importlib.reload(service)
    DistributionCollector(client, str(world["data"])).cycle()
    DistributionCollector(client, str(world["data"])).cycle()
    assert client.calls == [first_report, first_report]
    assert json.loads(journal.read_bytes())["status"] == "acked"
    assert len(service._load()["reports"]) == 1


def test_conflicting_duplicate_and_simultaneous_same_report(world):
    manifest, shard = output(world)
    config = config_for(world, manifest)
    report = report_for(world, manifest, shard, config)
    with ThreadPoolExecutor(max_workers=2) as pool:
        acks = list(pool.map(service.accept_report, [report, report]))
    assert acks[0] == acks[1] and len(service._load()["reports"]) == 1
    conflict = dict(report, bin_counts=[2, 4])
    conflict["report_hash"] = sha({k: v for k, v in conflict.items() if k != "report_hash"})
    with pytest.raises(HTTPException) as error:
        service.accept_report(conflict)
    assert error.value.status_code == 409
    assert service.get_current(config["config_id"], "silo-1")["bin_counts"] == [3, 3]


def test_new_output_changes_current_older_delivery_does_not_and_baseline_is_frozen(world):
    manifest, shard = output(world)
    config = config_for(world, manifest)
    before = report_for(world, manifest, shard, config)
    newer, newer_shard = output(world, "job-2", values=["20", "30"],
                                completed_at="2026-10-20T00:02:30+00:00")
    after = report_for(world, newer, newer_shard, config)
    service.accept_report(after)
    service.accept_report(before)
    assert service.get_current(config["config_id"], "silo-1") == after
    baseline = service.select_baseline(before["report_id"])
    reset_repositories()
    importlib.reload(service)
    assert service.get_current(config["config_id"], "silo-1", baseline=True) == baseline
    assert baseline["report"]["bin_counts"] == [3, 3]
    assert after["bin_counts"] == [0, 2] and before["report_id"] != after["report_id"]
    service.select_baseline(after["report_id"])
    assert service.get_baseline(baseline["baseline_id"]) == baseline


@pytest.mark.parametrize("field,value", [("bin_counts", [True, 5]), ("bin_counts", [2.0, 4]),
    ("bin_counts", [-1, 7]), ("bin_counts", [1, 1]), ("total_count", 0),
    ("excluded_count", -1), ("bin_edges", [0, 9, 20]), ("schema_fingerprint", "f" * 64),
    ("recipe_hash", "f" * 64), ("window_start", "2026-10-20T00:00:00+00:00")])
def test_strict_counts_edges_schema_and_window_rejected(world, field, value):
    manifest, shard = output(world)
    config = config_for(world, manifest)
    body = dict(report_for(world, manifest, shard, config), **{field: value})
    body["report_hash"] = sha({k: v for k, v in body.items() if k != "report_hash"})
    with pytest.raises(HTTPException) as error:
        service.accept_report(body)
    assert error.value.status_code == 422
    with pytest.raises(HTTPException) as missing:
        service.get_current(config["config_id"], "silo-1")
    assert missing.value.status_code == 404


def test_claimed_success_provenance_and_node_scope_are_not_trusted(world):
    manifest, shard = output(world)
    config = config_for(world, manifest)
    report = report_for(world, manifest, shard, config)
    for patch in ({"attempt_id": "foreign"}, {"output_hash": "f" * 64}, {"job_id": "absent"}):
        body = dict(report, **patch)
        from silo_sdk.distributions import report_identity
        body["report_id"] = report_identity(body)
        body["report_hash"] = sha({k: v for k, v in body.items() if k != "report_hash"})
        with pytest.raises(HTTPException) as error:
            service.accept_report(body)
        assert error.value.status_code in (404, 409)
    assert service.list_configs("silo-2") == []
    with pytest.raises(HTTPException):
        service.get_current(config["config_id"], "silo-2")


def test_store_failure_does_not_ack_or_publish_current_and_same_process_can_retry(world, monkeypatch):
    manifest, shard = output(world)
    config = config_for(world, manifest)
    report = report_for(world, manifest, shard, config)
    original = service._save
    def fail(_state):
        raise OSError("injected-save-failure")
    monkeypatch.setattr(service, "_save", fail)
    with pytest.raises(OSError):
        service.accept_report(report)
    assert service._load()["reports"] == {} and service._load()["current"] == {}
    monkeypatch.setattr(service, "_save", original)
    ack = service.accept_report(report)
    reset_repositories()
    assert service.accept_report(report) == ack


def test_empty_nonfinite_and_corrupt_local_output_never_become_normal_zero(world):
    manifest, _ = output(world, values=["NaN", "Inf", "bad"])
    config = config_for(world, manifest)
    client = Bridge()
    collector = DistributionCollector(client, str(world["data"]))
    collector.cycle()
    assert client.calls == []
    assert json.loads(next(collector.directory.glob("*.json")).read_bytes())["status"] == "blocked"
    with pytest.raises(HTTPException) as error:
        service.get_current(config["config_id"], "silo-1")
    assert error.value.status_code == 404
    assert histogram([], "x", [0, 1]) == {"bin_counts": [0], "total_count": 0, "valid_count": 0, "excluded_count": 0}


@pytest.mark.parametrize("kind", ["empty", "corrupt"])
def test_failed_collection_preserves_successful_cleaning_and_existing_training_input(world, kind):
    manifest, _ = output(world)
    config = config_for(world, manifest)
    if kind == "empty":
        output(world, "job-2", values=[])
    else:
        bad, _ = output(world, "job-2")
        (world["data"] / ".cleaned" / bad["output_id"] / "rows.json").write_text("[]", encoding="utf-8")
    original = jobs.get_job("job-1").model_dump()
    client = Bridge()
    DistributionCollector(client, str(world["data"])).cycle()
    assert jobs.get_job("job-1").model_dump() == original
    assert jobs.get_job("job-2").status == "completed"  # 분포 오류가 정제 결과를 덮지 않는다.
    stored, _ = load_output(str(world["data"]), manifest)
    trained = train_iterative_ridge(stored, ["x"], "y", initial_parameters=[0, 0],
                                    l2=0, step_size=0.000001, steps=1)
    assert trained.sample_count == 6
    assert service.get_current(config["config_id"], "silo-1")["output_id"] == manifest["output_id"]
    statuses = [json.loads(p.read_bytes())["status"] for p in (world["data"] / ".distribution" / "reports").glob("*.json")]
    assert sorted(statuses) == ["acked", "blocked"]


def test_local_journal_failure_sends_nothing_then_retries_same_output_without_reclean(world, monkeypatch):
    manifest, _ = output(world)
    config_for(world, manifest)
    job_before = jobs.get_job("job-1").model_dump()
    client = Bridge()
    original = distribution_runtime._atomic
    def fail(_path, _value):
        raise OSError("injected-local-save")
    monkeypatch.setattr(distribution_runtime, "_atomic", fail)
    with pytest.raises(OSError):
        DistributionCollector(client, str(world["data"])).cycle()
    assert client.calls == [] and jobs.get_job("job-1").model_dump() == job_before
    monkeypatch.setattr(distribution_runtime, "_atomic", original)
    DistributionCollector(client, str(world["data"])).cycle()
    assert len(client.calls) == 1 and client.calls[0]["output_id"] == manifest["output_id"]
    assert jobs.get_job("job-1").model_dump() == job_before


def test_transient_local_read_failure_is_durable_and_retry_does_not_change_successful_job(world, monkeypatch):
    manifest, _ = output(world)
    config = config_for(world, manifest)
    original = distribution_runtime.load_output
    def unavailable(*_args):
        raise OSError("transient local read")
    monkeypatch.setattr(distribution_runtime, "load_output", unavailable)
    client = Bridge()
    collector = DistributionCollector(client, str(world["data"]))
    job_before = jobs.get_job("job-1").model_dump()
    collector.cycle()
    journal = next(collector.directory.glob("*.json"))
    assert json.loads(journal.read_bytes()) == {"status": "retry", "report": None, "error_code": "local_output_io"}
    assert client.calls == [] and jobs.get_job("job-1").model_dump() == job_before
    monkeypatch.setattr(distribution_runtime, "load_output", original)
    DistributionCollector(client, str(world["data"])).cycle()
    assert json.loads(journal.read_bytes())["status"] == "acked"
    assert client.calls[0]["report_id"] == journal.stem
    assert service.get_current(config["config_id"], "silo-1")["output_id"] == manifest["output_id"]
    assert jobs.get_job("job-1").model_dump() == job_before


def test_wrong_ack_stays_pending_and_permanent_rejection_stays_separate_from_cleaning(world):
    manifest, _ = output(world)
    config_for(world, manifest)
    class WrongAck(Bridge):
        def push_distribution_report(self, report):
            return dict(super().push_distribution_report(report), report_hash="f" * 64)
    collector = DistributionCollector(WrongAck(), str(world["data"]))
    collector.cycle()
    journal = next(collector.directory.glob("*.json"))
    pending = json.loads(journal.read_bytes())
    assert pending["status"] == "pending" and pending["report"]["report_id"] == journal.stem
    class Rejected(Bridge):
        def push_distribution_report(self, report):
            raise SiloClientError(409, "conflict")
    DistributionCollector(Rejected(), str(world["data"])).cycle()
    blocked = json.loads(journal.read_bytes())
    assert blocked["status"] == "blocked" and blocked["report"] == pending["report"]
    assert jobs.get_job("job-1").status == "completed"


def test_corrupt_pending_journal_is_preserved_without_blocking_other_outputs(world):
    manifest, _ = output(world)
    config = config_for(world, manifest)
    collector = DistributionCollector(Bridge(), str(world["data"]))
    collector.cycle()
    journal = next(collector.directory.glob("*.json"))
    journal.write_bytes(b'{"status":"pending","report":{}}')
    damaged = journal.read_bytes()
    output(world, "job-2", completed_at="2026-10-20T00:02:30+00:00")
    collector.cycle()
    assert journal.read_bytes() == damaged
    assert service.get_current(config["config_id"], "silo-1")["job_id"] == "job-2"


def test_invalid_persisted_ledger_fails_closed_in_both_storage_modes(world):
    manifest, _ = output(world)
    config_for(world, manifest)
    repository = service._repository()
    repository.save({"state": {}})
    with pytest.raises(HTTPException) as error:
        service.list_configs()
    assert error.value.status_code == 503
    assert repository.load() == {"state": {}}  # 읽기가 손상 원장을 빈 성공으로 덮지 않는다.


def test_acked_outputs_do_not_starve_new_outputs_at_batch_limit(world):
    manifest, _ = output(world)
    config = config_for(world, manifest)
    output(world, "job-2", completed_at="2026-10-20T00:02:30+00:00")
    output(world, "job-3", completed_at="2026-10-20T00:03:30+00:00")
    client = Bridge()
    collector = DistributionCollector(client, str(world["data"]))
    for _ in range(4):
        collector.cycle(limit=1)
    assert len(client.calls) == 3
    assert service.get_current(config["config_id"], "silo-1")["job_id"] == "job-3"


def test_yaml_to_sqlite_migration_preserves_report_identity_and_baseline(world, monkeypatch):
    if world["mode"] != "yaml":
        return
    from storage.migration import import_yaml_to_sqlite
    manifest, shard = output(world)
    config = config_for(world, manifest)
    report = report_for(world, manifest, shard, config)
    ack = service.accept_report(report)
    baseline = service.select_baseline(report["report_id"])
    import_yaml_to_sqlite(settings.CONFIG_DIR)
    monkeypatch.setenv("FED_STORAGE", "sqlite")
    reset_repositories()
    assert service.get_current(config["config_id"], "silo-1") == report
    assert service.accept_report(report) == ack
    assert service.get_current(config["config_id"], "silo-1", baseline=True) == baseline


def test_config_scope_model_and_feature_contract_and_no_implicit_baseline(world):
    manifest, _ = output(world)
    config = config_for(world, manifest)
    assert config_for(world, manifest) == config
    for changes in ({"feature": "y"}, {"feature": "id"}, {"node_ids": ["unknown"]},
                    {"recipe_hash": "f" * 64}, {"feature_columns": ["x", "x"]},
                    {"feature_columns": ["x", "other"]}, {"target_column": "unknown"}):
        with pytest.raises(HTTPException):
            config_for(world, manifest, **changes)
    with pytest.raises(HTTPException) as missing:
        service.get_current(config["config_id"], "silo-1", baseline=True)
    assert missing.value.status_code == 404


def test_clean_loop_collects_without_any_training_round(world):
    manifest, _ = output(world)
    config = config_for(world, manifest)
    bridge = Bridge()
    async def scenario():
        task = asyncio.create_task(cleaning_runtime.run(bridge, str(world["data"]), poll_interval=0.01))
        try:
            for _ in range(200):
                if bridge.calls:
                    break
                await asyncio.sleep(0.01)
            assert bridge.calls
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(scenario())
    assert service.get_current(config["config_id"], "silo-1")["valid_count"] == 6


def test_api_and_legacy_baseline_contracts_remain_separate(world):
    manifest, shard = output(world)
    config = config_for(world, manifest)
    report = report_for(world, manifest, shard, config)
    client = TestClient(app)
    root = "/api/monitoring/distributions"
    assert client.get(root + "/configs", params={"node_id": "silo-1"}).json() == [config]
    ack = client.post(root + "/reports", json=report)
    assert ack.status_code == 200 and ack.json()["report_hash"] == report["report_hash"]
    assert client.post(root + "/baselines", json={"report_id": report["report_id"]}).status_code == 200
    assert client.get(root + "/current", params={"config_id": config["config_id"], "node_id": "silo-1"}).json() == report
    bad = client.post(root + "/reports", json=dict(report, rows=[PRIVATE]))
    assert bad.status_code == 422 and PRIVATE not in bad.text
    drift_detector.set_baseline(BaselineRequest(model_name="m", version="1.0.0", feature="x",
                                              bin_edges=[0, 1], bin_counts=[10]))
    assert drift_detector.get_baseline("m", "1.0.0", "x")["bin_counts"] == [10]
    assert service.get_current(config["config_id"], "silo-1", baseline=True)["report"]["bin_counts"] == [3, 3]


@pytest.mark.parametrize("bad", [[0, 0], [1, 0], [0, float("nan")], [0, float("inf")], [False, 1], [0, 10 ** 1000]])
def test_invalid_common_edges_are_rejected(bad):
    with pytest.raises(ValueError):
        edges(bad)


def test_numeric_exclusions_clip_and_internal_boundary_have_independent_expected_counts():
    values = [-10, 0, 9.9, 10, 20, 100, True, False, None, float("nan"), float("inf"), "bad"]
    assert histogram([{"x": v} for v in values], "x", [0, 10, 20]) == {
        "bin_counts": [3, 3], "total_count": 12, "valid_count": 6, "excluded_count": 6}


def test_sdk_preserves_legacy_push_and_binds_new_report_sender(monkeypatch):
    client = SiloClient("http://127.0.0.1:1", "silo-1")
    calls = []
    def request(method, path, body=None, **kwargs):
        calls.append((method, path, body))
        return [] if method == "GET" else {"accepted": True}
    monkeypatch.setattr(client, "_request", request)
    client.list_distribution_configs()
    client.push_distribution_report({"node_id": "silo-1"})
    client.push_distribution("m", "1.0.0", "x", [0, 1], [5])
    assert calls[0][1] == "/api/monitoring/distributions/configs?node_id=silo-1"
    assert calls[1][1] == "/api/monitoring/distributions/reports"
    assert calls[2][1] == "/api/monitoring/drift"
    with pytest.raises(ValueError):
        client.push_distribution_report({"node_id": "silo-2"})
