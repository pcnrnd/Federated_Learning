"""G3-F1: YAML job과 YAML/SQLite round 사이 모든 opening 게시 경계."""
import importlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from models.federated_schemas import LiveLearning, ParameterContribution, TrainingJobRequest
from services import training_job_service as jobs, training_round_service as rounds
from silo_sdk.training_runtime import LiveWorker
from storage.factory import reset_repositories
from test_live_training import seed


def setup_job(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("FED_STORAGE", backend)
    reset_repositories()
    ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    monkeypatch.setattr(jobs.resource_service, "group_has_pressure", lambda _nodes: False)
    jobs.create_job(TrainingJobRequest(job_id="durable", model_name="m", version="1.0.0",
        group_id="root", cleaning_job_id="cleaned", learning=LiveLearning(),
        min_contributions=2, max_rounds=2))
    return ids, data


def finish(entry, ids, data):
    class Local:
        api_key = None
        def __init__(self, node):
            self.silo_id = node

        def push_live_parameters(self, value):
            return rounds.submit_contribution(ParameterContribution(**value)).model_dump()
    workers = [LiveWorker(Local(node), str(data[node])) for node in ids]
    for worker in workers:
        assert worker.process_round(entry.model_dump())
        assert worker.process_round(entry.model_dump())  # own/outbox ACK 재사용, 재합산 없음.
    result = rounds.aggregate_round(entry.round_id)
    assert len(rounds.list_contributions(entry.round_id)) == len(ids)
    assert result.total_samples == sum(origin["sample_count"] for origin in result.origins)
    return result


@pytest.mark.parametrize("backend", ["yaml", "sqlite"])
@pytest.mark.parametrize("boundary", ["intent_before", "intent_after", "round_before", "round_after", "link_before", "link_after"])
def test_opening_save_failure_same_process_then_reload_converges_to_one_round(tmp_path, monkeypatch, backend, boundary):
    ids, data = setup_job(tmp_path, monkeypatch, backend)
    save_job, save_round = jobs.save_training_jobs, rounds._save_round
    injected = []

    def interrupt_job(values):
        value = values["durable"]
        stage = "link" if value.get("current_round_id") else "intent" if value.get("opening_intent") else None
        if not injected and boundary.startswith(str(stage) + "_"):
            injected.append(stage)
            if boundary.endswith("after"):
                save_job(values)
            raise OSError("injected durable opening boundary")
        save_job(values)

    def interrupt_round(entry):
        if not injected and boundary.startswith("round_") and entry.job_id == "durable":
            injected.append("round")
            if boundary.endswith("after"):
                save_round(entry)
            raise OSError("injected round publication boundary")
        save_round(entry)

    monkeypatch.setattr(jobs, "save_training_jobs", interrupt_job)
    monkeypatch.setattr(rounds, "_save_round", interrupt_round)
    with pytest.raises(OSError):
        jobs.tick(max_concurrent_rounds=1)
    assert injected
    before = jobs.get_job("durable")
    assert before.rounds_completed == before.rounds_failed == 0
    published = rounds.list_rounds()
    assert len(published) <= 1
    if boundary == "intent_before":
        assert before.opening_intent is None and not published
    elif boundary in ("intent_after", "round_before"):
        assert before.opening_intent is not None and not published
    elif boundary in ("round_after", "link_before"):
        assert before.opening_intent.round_id == published[0].round_id
        assert before.current_round_id is None
    else:
        assert before.current_round_id == published[0].round_id
    # 같은 프로세스에서도 저장되지 않은 intent를 기억해 실행하지 않아야 한다.
    jobs.tick(max_concurrent_rounds=1)
    first_id = jobs.get_job("durable").current_round_id
    assert first_id and len(rounds.list_rounds()) == 1
    importlib.reload(jobs)
    importlib.reload(rounds)
    reset_repositories()
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: jobs.tick(max_concurrent_rounds=1), range(6)))
    assert jobs.get_job("durable").current_round_id == first_id
    first = rounds.get_round(first_id)
    assert first.job_id == "durable" and first.job_occurrence == 1
    result = finish(first, ids, data)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: jobs.tick(max_concurrent_rounds=1), range(6)))
    linked = jobs.get_job("durable")
    assert linked.rounds_completed == 1 and linked.rounds_failed == 0
    second = rounds.get_round(linked.current_round_id)
    assert second.job_occurrence == 2 and second.parent_round_id == first_id
    assert second.base_parameters == result.parameters and second.base_checksum == result.checksum
    finish(second, ids, data)
    for _ in range(3):
        jobs.tick(max_concurrent_rounds=1)
    final = jobs.get_job("durable")
    assert final.status == "completed" and final.rounds_completed == final.max_rounds == 2
    assert final.rounds_failed == 0 and final.current_round_id is None and final.opening_intent is None
    assert len(rounds.list_rounds()) == 2


@pytest.mark.parametrize("backend", ["yaml", "sqlite"])
def test_opening_retry_uses_frozen_request_and_reattaches_even_if_capacity_full(tmp_path, monkeypatch, backend):
    setup_job(tmp_path, monkeypatch, backend)
    original = jobs.save_training_jobs
    def fail_link(values):
        if values["durable"].get("current_round_id"):
            raise OSError("round exists but link unavailable")
        original(values)
    monkeypatch.setattr(jobs, "save_training_jobs", fail_link)
    with pytest.raises(OSError):
        jobs.tick(max_concurrent_rounds=1)
    expected = rounds.list_rounds()[0]
    monkeypatch.setattr(jobs, "save_training_jobs", original)
    # 원래의 그룹을 다시 검증해서 이미 실행 중인 동결 회차를 버리면 안 된다.
    from services import silo_group_service
    silo_group_service.delete_group("root")
    importlib.reload(jobs)
    jobs.tick(max_concurrent_rounds=0)
    assert jobs.get_job("durable").current_round_id == expected.round_id
    assert rounds.get_round(expected.round_id).member_snapshot == expected.member_snapshot
    assert len(rounds.list_rounds()) == 1
