"""실제 로컬 정제/수치 학습·HTTP 계층·feedback·저장 실패 경계."""
from __future__ import annotations

import copy
import importlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from config.server_manager import save_servers
from models.cleaning_schemas import CleaningJobCreate, CleaningRecipeRequest, ShardReport
from models.federated_schemas import LiveLearning, ParameterContribution, SiloGroupRequest, TrainingJobRequest, TrainingRoundCreate, TrainingExecutionFailure
from models.packaging_schemas import ModelRegisterRequest
from services import cleaning_job_service as cleaning_jobs, cleaning_recipe_service, model_registry, silo_group_service
from services import training_job_service as jobs, training_round_service as rounds
from silo_sdk import cleaning_output, synthetic, training_protocol as wire
from silo_sdk.client import SiloClient
from silo_sdk.training_runtime import LiveWorker, make_server
from silo_sdk import training_runtime


@contextmanager
def serve(server):
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


@contextmanager
def central_http():
    # SDK의 중앙 hop도 실제 HTTP socket을 사용하고 기존 ASGI 라우터를 통과한다.
    from main import app
    api = TestClient(app)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def dispatch(self):
            content = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            response = api.request(self.command, self.path, content=content,
                headers={"Content-Type": "application/json", "X-FED-API-Key": self.headers.get("X-FED-API-Key", "")})
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)
        do_GET = dispatch
        do_POST = dispatch
    try:
        with serve(ThreadingHTTPServer(("127.0.0.1", 0), Handler)) as url:
            yield url
    finally:
        api.close()


def seed(tmp_path, count=6, hierarchy=True):
    ids = [f"silo-{i}" for i in range(1, count + 1)]
    save_servers({node: {"base_url": f"tcp://{node}:2375", "role": "client"} for node in ids})
    weights = tmp_path / "seed-model.json"
    weights.write_text('{"parameters":[0,0,0,0]}', encoding="utf-8")
    model_registry.register_model(ModelRegisterRequest(name="m", version="1.0.0", framework="pytorch",
                                                      weights_path=str(weights)))
    roots = [ids[0], ids[3]] if hierarchy else ids
    silo_group_service.create_group(SiloGroupRequest(group_id="root", member_node_ids=roots))
    if hierarchy:
        for identity, root, children in (("left", ids[0], ids[1:3]), ("right", ids[3], ids[4:6])):
            silo_group_service.create_group(SiloGroupRequest(group_id=identity, aggregator_node_id=root,
                                                            member_node_ids=children))
    cleaning_recipe_service.register_recipe(CleaningRecipeRequest(name="hvc", version="1.0.0",
        steps=synthetic.HVC_STEPS, mapping=synthetic.HVC_MAPPING))
    cleaning_jobs.create_job(CleaningJobCreate(job_id="cleaned", recipe_name="hvc", recipe_version="1.0.0",
                                              group_id="root", dataset_label="silo-sources"))
    data, local_rows = {}, {}
    recipe = cleaning_recipe_service.get_recipe("hvc", "1.0.0").model_dump()
    for node in ids:
        index = next(shard.shard_index for shard in cleaning_jobs.get_job("cleaned").shards if shard.silo_id == node)
        directory = tmp_path / node
        synthetic.write_sources(node, directory)  # 명시적인 test fixture 생성뿐. live 경로에는 없다.
        job = cleaning_jobs.start_shard("cleaned", index, node, f"claim-{node}")
        shard = job.shards[index]
        manifest = cleaning_output.execute(str(directory), node, job.model_dump(), shard.model_dump(), recipe)
        cleaning_jobs.report_shard(ShardReport(job_id="cleaned", shard_index=index, silo_id=node,
            attempt_id=shard.attempt_id, started_at="t", completed_at="t", **{key: manifest[key] for key in
            ("rows_in", "rows_out", "step_counters", "output_id", "output_hash", "source_hash", "recipe_hash", "schema_fingerprint")}))
        data[node] = directory
        local_rows[node] = cleaning_output.load_output(str(directory), manifest)[0]
    return ids, roots, data, local_rows


def request(**extra):
    return TrainingRoundCreate(model_name="m", version="1.0.0", group_id="root", cleaning_job_id="cleaned",
        min_contributions=extra.pop("min_contributions", 2), learning=LiveLearning(), **extra)


def independent_step(rows, base, rate=0.0001, l2=0.001):
    n = len(rows)
    errors = [sum(base[j] * row[f"x{j+1}"] for j in range(3)) + base[-1] - row["y"] for row in rows]
    gradients = [sum(error * row[f"x{j+1}"] for row, error in zip(rows, errors)) / n + l2 * base[j] for j in range(3)]
    gradients.append(sum(errors) / n)
    return [p - rate * gradient for p, gradient in zip(base, gradients)]


def independent_loss(rows, values):
    squared = [(sum(values[j] * row[f"x{j+1}"] for j in range(3)) + values[-1] - row["y"]) ** 2 for row in rows]
    return sum(squared) / (2 * len(rows)) + 0.001 * sum(p * p for p in values[:-1]) / 2


def test_http_two_rounds_feedback_and_weighted_independent_gradient(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "API_KEY", None)
    ids, roots, data, local_rows = seed(tmp_path)
    all_rows = [row for rows in local_rows.values() for row in rows]
    with ExitStack() as stack:
        central = stack.enter_context(central_http())
        workers = {node: LiveWorker(SiloClient(central, node, retries=0, timeout=3), str(data[node])) for node in ids}
        endpoints = {node: "http://127.0.0.1:8081" for node in ids}
        for node in roots:
            endpoints[node] = stack.enter_context(serve(make_server(workers[node], ("127.0.0.1", 0))))
        job = jobs.create_job(TrainingJobRequest(job_id="live", model_name="m", version="1.0.0", group_id="root",
            cleaning_job_id="cleaned", learning=LiveLearning(), worker_endpoints=endpoints, min_contributions=2, max_rounds=2))
        monkeypatch.setattr(jobs.resource_service, "group_has_pressure", lambda _nodes: False)
        previous, base = None, [0.0] * 4
        for index in range(2):
            assert jobs.tick() == [job.job_id]
            entry = rounds.get_round(jobs.get_job(job.job_id).current_round_id).model_dump()
            assert entry["parent_round_id"] == previous
            assert entry["base_parameters"] == base
            assert entry["base_checksum"] == wire.parameter_checksum(base)
            for node in roots:
                assert workers[node].process_round(entry) is False  # 자기 학습은 하고 child 수신 대기.
            for node in set(ids) - set(roots):
                assert workers[node].process_round(entry) is True  # 실제 HTTP child→root.
            # 재시작은 디스크 inbox/outbox를 사용한다. fixture 원천을 바꿔도 재정제하지 않는다.
            for node in ids:
                for filename in synthetic.SOURCE_FILES.values():
                    (data[node] / filename).unlink(missing_ok=True)
                workers[node] = LiveWorker(SiloClient(central, node, retries=0, timeout=3), str(data[node]))
            for root_index, node in enumerate(roots):
                assert workers[node].process_round(entry) is True  # 실제 HTTP root→central.
                if root_index == 0:
                    with pytest.raises(HTTPException) as insufficient:
                        rounds.aggregate_round(entry["round_id"])
                    assert insufficient.value.status_code == 400
            result = rounds.aggregate_round(entry["round_id"])
            assert result.parameters == pytest.approx(independent_step(all_rows, base), abs=1e-12)
            flat = [sum(leaf["sample_count"] * leaf["parameters"][j] for leaf in result.origins)
                    / result.total_samples for j in range(4)]
            assert result.parameters == pytest.approx(flat, abs=1e-12)
            assert result.total_samples == len(all_rows)
            assert {leaf["silo_id"] for leaf in result.origins} == set(ids)
            assert all(leaf["base_checksum"] == entry["base_checksum"] for leaf in result.origins)
            assert result.parameters == rounds.get_round(entry["round_id"]).result["parameters"]
            assert workers[roots[0]].client.get_result(entry["round_id"])["checksum"] == result.checksum
            assert rounds.aggregate_round(entry["round_id"]).result_id == result.result_id
            print(json.dumps({"round": index+1, "round_id": entry["round_id"], "base_checksum": entry["base_checksum"],
                "result_checksum": result.checksum, "result_id": result.result_id, "sample_count": result.total_samples,
                "origins": {leaf["silo_id"]: leaf["sample_count"] for leaf in result.origins},
                "flat_hier_max_error": max(abs(left-right) for left, right in zip(flat, result.parameters)),
                "objective": independent_loss(all_rows, result.parameters)}))
            previous, base = entry["round_id"], result.parameters
        jobs.tick()
        assert jobs.get_job(job.job_id).status == "completed"
        assert independent_loss(all_rows, base) < independent_loss(all_rows, [0.0] * 4)
        wire_text = json.dumps(rounds.get_result(previous).model_dump())
        assert '"records"' not in wire_text and '"rows"' not in wire_text and '"id"' not in wire_text


def leaves_for_flat(tmp_path):
    ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    entry = rounds.create_round(request()).model_dump()
    class Local:
        def __init__(self, node):
            self.silo_id, self.api_key = node, None
        def push_live_parameters(self, envelope):
            return rounds.submit_contribution(ParameterContribution(**envelope)).model_dump()
    envelopes = []
    for node in ids:
        worker = LiveWorker(Local(node), str(data[node]))
        assert worker.process_round(entry)
        path = worker.round_path(data[node] / ".training", entry["round_id"])
        envelopes.append(json.loads((path / "envelope.json").read_bytes()))
    return entry, envelopes, data


@pytest.mark.parametrize("field", ["checksum", "sample_count", "base_checksum", "space_checksum", "aggregated_from", "origins"])
def test_reject_forged_or_overlapping_live_envelope(tmp_path, field):
    entry, envelopes, _data = leaves_for_flat(tmp_path)
    payload = copy.deepcopy(envelopes[0])
    if field == "origins":
        payload[field] += payload[field]
    elif field == "aggregated_from":
        payload[field] = [payload["silo_id"]]
    elif field == "sample_count":
        payload[field] += 1
    else:
        payload[field] = "0" * 64
    with pytest.raises(HTTPException) as exc:
        rounds.submit_contribution(ParameterContribution(**payload))
    assert exc.value.status_code == 422
    assert rounds.get_round(entry["round_id"]).total_samples == sum(item["sample_count"] for item in envelopes)


@pytest.mark.parametrize("backend", ["yaml", "sqlite"])
def test_ledger_ack_loss_and_atomic_completion_restart(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("FED_STORAGE", backend)
    entry, envelopes, _data = leaves_for_flat(tmp_path)
    original = rounds._save_round
    seen_completed = []
    def fail_completed(value):
        if value.status == "completed":
            assert value.result["parameters"] and value.result["checksum"]
            seen_completed.append(value.model_dump())
            # 실제 게시 전 동시 GET은 아직 aggregating이며 completed를 보지 못한다.
            observed = rounds.get_round(value.round_id)
            assert observed.status == "aggregating" and observed.result is None
            raise OSError("controlled failure before atomic completed publication")
        original(value)
    monkeypatch.setattr(rounds, "_save_round", fail_completed)
    with pytest.raises(OSError):
        rounds.aggregate_round(entry["round_id"])
    importlib.reload(rounds)
    assert rounds.get_round(entry["round_id"]).status == "aggregating"
    result = rounds.aggregate_round(entry["round_id"])
    assert result.result_id == seen_completed[0]["result"]["result_id"]
    # 응답 유실 후 같은 envelope는 완료 후에도 같은 ACK, 다른 payload는 거부.
    ack = rounds.submit_contribution(ParameterContribution(**envelopes[0]))
    assert ack.envelope_checksum == envelopes[0]["envelope_checksum"]
    assert rounds.get_round(entry["round_id"]).result["parameters"] == result.parameters
    assert rounds.get_result(entry["round_id"]).checksum == wire.parameter_checksum(result.parameters)


def test_ledger_saved_statistics_failure_recovers_same_origin(tmp_path, monkeypatch):
    ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    entry = rounds.create_round(request()).model_dump()
    original = rounds._save_round
    fail = [True]
    def interrupted(value):
        if value.contributors and fail[0]:
            fail[0] = False
            raise OSError("ledger durable; statistics publication failed")
        original(value)
    class Local:
        silo_id, api_key = ids[0], None
        def push_live_parameters(self, value):
            return rounds.submit_contribution(ParameterContribution(**value)).model_dump()
    worker = LiveWorker(Local(), str(data[ids[0]]))
    monkeypatch.setattr(rounds, "_save_round", interrupted)
    with pytest.raises(OSError):
        worker.process_round(entry)
    assert rounds.get_round(entry["round_id"]).contributors == []
    importlib.reload(rounds)
    assert worker.process_round(entry)
    current = rounds.get_round(entry["round_id"])
    assert current.contributors == [ids[0]] and current.total_samples > 0
    assert len(rounds.list_contributions(entry["round_id"])) == 1


def test_live_never_falls_back_to_fixture_or_wrong_base(tmp_path):
    ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    entry = rounds.create_round(request()).model_dump()
    reference = entry["cleaning_snapshot"][ids[0]]
    (data[ids[0]] / ".cleaned" / reference["output_id"] / "rows.json").unlink()
    worker = LiveWorker(SiloClient("http://unused", ids[0]), str(data[ids[0]]))
    with pytest.raises(FileNotFoundError):
        worker.process_round(entry)
    assert rounds.get_round(entry["round_id"]).contributors == []
    with pytest.raises(HTTPException):
        rounds.create_round(request(parent_round_id=entry["round_id"]))


def test_http_child_ack_loss_receiver_restart_and_identity_guards(tmp_path, monkeypatch):
    ids, roots, data, _rows = seed(tmp_path)
    class Local:
        api_key, timeout = "fixture-only-key", 3
        def __init__(self, identity):
            self.silo_id = identity
        def get_round(self, identity):
            return rounds.get_round(identity).model_dump()
    root = LiveWorker(Local(roots[0]), str(data[roots[0]]))
    child = LiveWorker(Local(ids[1]), str(data[ids[1]]))
    with serve(make_server(root, ("127.0.0.1", 0))) as url:
        endpoints = {node: "http://127.0.0.1:8081" for node in ids}
        endpoints[roots[0]] = url
        entry = rounds.create_round(request(worker_endpoints=endpoints)).model_dump()
        assert root.process_round(entry) is False
        original_send = child.send
        def lost_ack(endpoint, leaf):
            original_send(endpoint, leaf)  # 서버 내구 수신까지 실제 완료한 후 응답 유실.
            raise TimeoutError("controlled ACK loss")
        monkeypatch.setattr(child, "send", lost_ack)
        with pytest.raises(TimeoutError):
            child.process_round(entry)
        port = urllib.parse.urlparse(url).port
    # receiver 객체/HTTP 서버를 재생성한다. 디스크가 유일한 inbox/outbox 상태이다.
    root = LiveWorker(Local(roots[0]), str(data[roots[0]]))
    child = LiveWorker(Local(ids[1]), str(data[ids[1]]))
    def no_retraining(*_args, **_kwargs):
        pytest.fail("응답 유실 복구에서 성공 own-result를 재학습함")
    monkeypatch.setattr(training_runtime, "train_iterative_ridge", no_retraining)
    with serve(make_server(root, ("127.0.0.1", port))) as restarted_url:
        assert child.process_round(entry)
        child_path = child.round_path(data[ids[1]] / ".training", entry["round_id"])
        leaf = json.loads((child_path / "own.json").read_bytes())
        ack = json.loads((child_path / "parent_ack.json").read_bytes())
        root_path = root.round_path(data[roots[0]] / ".training", entry["round_id"])
        inbox = root_path / "inbox" / f"{wire.digest(ids[1])}.json"
        assert json.loads(inbox.read_bytes())["ack"] == ack
        with pytest.raises(PermissionError):
            root.receive(ids[1], leaf, "203.0.113.1")
        for key, sender_header, expected in (("wrong", ids[1], 401), (Local.api_key, ids[2], 422)):
            forged = urllib.request.Request(restarted_url + f"/api/worker/contributions/{ids[1]}",
                data=wire.encoded(leaf), method="POST", headers={"X-FED-API-Key": key,
                "X-FED-Silo-ID": sender_header, "Content-Type": "application/json"})
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(forged, timeout=3)
            assert error.value.code == expected
        print(json.dumps({"round_id": entry["round_id"], "sender": ids[1], "receiver": roots[0],
                          "ack_id": ack["contribution_id"], "recovered_after_ack_loss": True}))


@pytest.mark.parametrize("change", ["base", "features", "output"])
def test_worker_rejects_changed_initial_model_or_cleaned_space(tmp_path, change):
    ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    entry = rounds.create_round(request()).model_dump()
    if change == "base":
        entry["base_parameters"][0] += 1
    elif change == "features":
        entry["learning"]["features"].reverse()
    else:
        entry["cleaning_snapshot"][ids[0]]["output_hash"] = "0" * 64
    with pytest.raises(ValueError):
        LiveWorker(SiloClient("http://unused", ids[0]), str(data[ids[0]])).process_round(entry)
    assert rounds.get_round(entry["round_id"]).contributors == []


def test_live_rejects_wrong_sample_arithmetic_raw_fields_and_child_central_submit(tmp_path):
    _ids, _roots, _data, _rows = seed(tmp_path)
    entry = rounds.create_round(request()).model_dump()
    with pytest.raises(ValueError):
        wire.combine_live(entry, "silo-2", [])  # leaf는 중앙 대표가 아니다.
    missing_self = [{"silo_id": "silo-2"}, {"silo_id": "silo-3"}]
    with pytest.raises(ValueError):
        wire.combine_live(entry, "silo-1", missing_self)
    with pytest.raises(HTTPException):
        rounds.submit_contribution(ParameterContribution(round_id=entry["round_id"], silo_id="silo-2",
            sample_count=1, parameters=[0.0]*4, origins=[]))


def test_completed_views_always_include_valid_durable_parameters(tmp_path, monkeypatch):
    entry, _envelopes, _data = leaves_for_flat(tmp_path)
    original = rounds._save_round
    before_publish, reader_requested, release = (threading.Event() for _ in range(3))
    observations = []
    def hold_publish(value):
        if value.status == "completed":
            before_publish.set()
            assert reader_requested.wait(3)
        original(value)
    def observer():
        assert before_publish.wait(3)
        reader_requested.set()
        observed = rounds.get_round(entry["round_id"])  # round lock은 원자 게시 완료까지 기다림.
        observations.append(observed)
        release.set()
    monkeypatch.setattr(rounds, "_save_round", hold_publish)
    reader = threading.Thread(target=observer)
    reader.start()
    try:
        result = rounds.aggregate_round(entry["round_id"])
        assert release.wait(3)
    finally:
        reader.join(timeout=3)
    assert not reader.is_alive()
    assert observations and all(observed.status == "completed" and observed.result["parameters"] == result.parameters
        and observed.result["checksum"] == result.checksum for observed in observations)


def test_cleaning_root_leaf_snapshot_is_immutable_and_overlap_is_rejected(tmp_path):
    from config.federated_manager import load_silo_groups, save_silo_groups
    ids, _roots, _data, _rows = seed(tmp_path)
    original = cleaning_jobs.get_job("cleaned")
    assert len(original.shards) == len(ids) and {shard.silo_id for shard in original.shards} == set(ids)
    first = rounds.create_round(request())
    assert set(first.cleaning_snapshot) == set(ids)
    groups = load_silo_groups()
    groups["left"]["member_node_ids"] = ["silo-2"]
    save_silo_groups(groups)  # 새 토폴로지 이후에도 이미 연 정제/라운드는 기존 snapshot 유지.
    assert cleaning_jobs.get_job("cleaned").model_dump() == original.model_dump()
    assert rounds.get_round(first.round_id).cleaning_snapshot == first.cleaning_snapshot
    with pytest.raises(HTTPException) as mismatch:
        rounds.create_round(request())
    assert mismatch.value.status_code == 409  # old6 출력을 새5 참여자로 몰래 줄여 학습하지 않음.
    groups["left"]["member_node_ids"] = ["silo-2", "silo-5"]
    save_silo_groups(groups)  # 손상/구형 설정에서 겹친 leaf도 묵시적으로 dedupe하지 않는다.
    with pytest.raises(HTTPException) as overlap:
        cleaning_jobs.create_job(CleaningJobCreate(job_id="overlap", recipe_name="hvc", recipe_version="1.0.0",
                                                  group_id="root", dataset_label="silo-sources"))
    assert overlap.value.status_code == 409


def test_permanent_input_failure_is_visible_and_ends_live_job_budget(tmp_path, monkeypatch):
    ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    job = jobs.create_job(TrainingJobRequest(job_id="bad-input", model_name="m", version="1.0.0",
        group_id="root", cleaning_job_id="cleaned", learning=LiveLearning(), max_rounds=1, min_contributions=2))
    monkeypatch.setattr(jobs.resource_service, "group_has_pressure", lambda _nodes: False)
    assert jobs.tick() == [job.job_id]
    entry = rounds.get_round(jobs.get_job(job.job_id).current_round_id).model_dump()
    reference = entry["cleaning_snapshot"][ids[0]]
    (data[ids[0]] / ".cleaned" / reference["output_id"] / "rows.json").unlink()
    class Local:
        silo_id = ids[0]
        def report_training_failure(self, identity, code):
            return rounds.report_execution_failure(identity, TrainingExecutionFailure(silo_id=self.silo_id, error_code=code))
    with pytest.raises(FileNotFoundError):
        LiveWorker(Local(), str(data[ids[0]])).attempt_round(entry)
    failed = rounds.get_round(entry["round_id"])
    assert failed.status == "failed" and failed.result is None
    assert failed.execution_errors[ids[0]]["error_code"] == "input_missing"
    assert str(data[ids[0]]) not in failed.error
    assert jobs.tick() == [] and jobs.get_job(job.job_id).status == "failed"
    with pytest.raises(HTTPException):
        rounds.aggregate_round(failed.round_id)


def test_leaf_count_arithmetic_and_raw_fields_cannot_hide_behind_new_checksum(tmp_path):
    entry, envelopes, _data = leaves_for_flat(tmp_path)
    leaf = copy.deepcopy(envelopes[0]["origins"][0])
    leaf["sample_count"] += 1
    leaf["contribution_id"] = wire.digest({k: v for k, v in leaf.items() if k != "contribution_id"})
    with pytest.raises(ValueError, match="표본"):
        wire.validate_leaf(entry, leaf)
    leaf = copy.deepcopy(envelopes[0]["origins"][0])
    leaf["rows"] = [{"sensitive": "must not be transmitted"}]
    with pytest.raises(ValueError, match="필드"):
        wire.validate_leaf(entry, leaf)
