"""일반 결과 등록의 분포 원장 독립성과 재교육 예약의 fail-closed 경계."""
import importlib

import pytest
from fastapi import HTTPException

from g4_helpers import completed_live_result
from models.federated_schemas import TrainingJobRequest
from services import distribution_service as ledger, model_registry, training_job_service as jobs
from services import training_model_service as registration, training_round_service as rounds
from storage.factory import reset_repositories


@pytest.fixture(params=["yaml", "sqlite"])
def completed(request, monkeypatch, tmp_path):
    monkeypatch.setenv("FED_STORAGE", request.param)
    reset_repositories()
    return completed_live_result(tmp_path)


def attach_job(result, owner=None):
    entry = rounds.get_round(result.round_id)
    job = jobs.create_job(TrainingJobRequest(job_id="ordinary-looking-job", model_name=entry.model_name,
        version=entry.version, group_id=entry.group_id, notes="retrain:이 메모는 소유권 증거가 아님",
        retraining_event_id=owner))
    rounds._save_round(entry.model_copy(update={"job_id": job.job_id}))
    return job


def fail_read():
    raise HTTPException(503, "분포 원장 read 실패")


@pytest.mark.parametrize("job_kind", ["jobless", "normal"])
@pytest.mark.parametrize("failure", ["read", "corrupt"])
def test_ordinary_registration_and_restart_do_not_read_distribution_ledger(completed, monkeypatch, job_kind, failure):
    if job_kind == "normal":
        attach_job(completed)
    if failure == "corrupt":
        ledger._repository().save({"not-a-distribution-ledger": True})
    else:
        monkeypatch.setattr(ledger, "_load", fail_read)
    registered = registration.register_completed_result(completed.round_id)
    importlib.reload(registration)
    importlib.reload(jobs)
    assert registration.register_completed_result(completed.round_id).version == registered.version
    assert len([m for m in model_registry.list_models() if m.metadata.get("result_id") == completed.result_id]) == 1


@pytest.mark.parametrize("failure", ["read", "save", "corrupt", "wrong-owner"])
def test_owned_registration_reserves_before_publication_and_recovers_from_reload(completed, monkeypatch, failure):
    owner = "a" * 64
    job = attach_job(completed, owner)
    state = ledger._load()
    state["retrain_events"][owner] = {"training_request": {"job_id": job.job_id,
        "retraining_event_id": owner}, "registration_result_ids": []}
    ledger._save(state)
    original_load, original_save = ledger._load, ledger._save
    if failure == "read":
        monkeypatch.setattr(ledger, "_load", fail_read)
    elif failure == "save":
        monkeypatch.setattr(ledger, "_save", lambda _state: (_ for _ in ()).throw(OSError("save failed")))
    elif failure == "corrupt":
        ledger._repository().save({"not-a-distribution-ledger": True})
    else:
        wrong = original_load()
        wrong["retrain_events"][owner]["training_request"]["job_id"] = "another-job"
        original_save(wrong)
    for _ in range(2):
        with pytest.raises((HTTPException, OSError)):
            registration.register_completed_result(completed.round_id)
        assert not [m for m in model_registry.list_models() if m.metadata.get("result_id") == completed.result_id]
        assert registration.list_registrations() == []
        importlib.reload(registration)
        importlib.reload(jobs)
        assert jobs.get_job(job.job_id).retraining_event_id == owner
    monkeypatch.setattr(ledger, "_load", original_load)
    monkeypatch.setattr(ledger, "_save", original_save)
    original_save(state)
    entry = registration.register_completed_result(completed.round_id)
    assert entry.metadata["result_id"] == completed.result_id
    assert original_load()["retrain_events"][owner]["registration_result_ids"] == [completed.result_id]
