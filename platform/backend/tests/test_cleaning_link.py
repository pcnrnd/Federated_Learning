"""정제 작업 ↔ 학습 연결 (F7) — cleaning_job_id 기록, 배정된 대기 샤드 조회"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from config.server_manager import save_servers
from models.cleaning_schemas import CleaningJobCreate, CleaningRecipeRequest, CleaningStep, ShardReport
from models.federated_schemas import SiloGroupRequest, TrainingJobRequest, TrainingRoundCreate
from models.packaging_schemas import ModelRegisterRequest
from services import (
    cleaning_job_service,
    cleaning_recipe_service,
    model_registry,
    silo_group_service,
    training_job_service,
    training_round_service,
)


def _complete(identity="c1"):
    for shard in cleaning_job_service.get_job(identity).shards:
        cleaning_job_service.report_shard(ShardReport(job_id=identity,
            shard_index=shard.shard_index, silo_id=shard.silo_id, rows_in=10, rows_out=8,
            started_at="2026-10-19T00:00:00Z", completed_at="2026-10-19T00:01:00Z",
            schema_fingerprint="a" * 64, output_id="b" * 64, output_hash="c" * 64,
            source_hash="d" * 64, recipe_hash="e" * 64))


@pytest.fixture(autouse=True)
def _seed(tmp_path):
    save_servers({
        f"silo-{i}": {"base_url": f"tcp://localhost:237{i}", "label": f"silo-{i}",
                      "type": "remote", "role": "client", "tls": False}
        for i in (1, 2, 3)
    })
    weights = tmp_path / "m.pt"
    weights.write_bytes(b"")
    model_registry.register_model(ModelRegisterRequest(
        name="alpha", version="1.0.0", framework="pytorch", weights_path=str(weights)))
    silo_group_service.create_group(SiloGroupRequest(group_id="g1",
                                                     member_node_ids=["silo-1", "silo-2"]))
    silo_group_service.create_group(SiloGroupRequest(group_id="g2", member_node_ids=["silo-3"]))
    cleaning_recipe_service.register_recipe(CleaningRecipeRequest(
        name="r", version="1.0.0",
        steps=[CleaningStep(type="dedupe", params={"keys": ["id"]})]))
    for job_id, group in (("c1", "g1"), ("c2", "g2")):
        cleaning_job_service.create_job(CleaningJobCreate(
            job_id=job_id, recipe_name="r", recipe_version="1.0.0", group_id=group,
            dataset_label="silo-sources"))


@pytest.mark.unit
def test_round_records_cleaning_job_id_and_checks_it_exists():
    with pytest.raises(HTTPException) as waiting:
        training_round_service.create_round(TrainingRoundCreate(
            model_name="alpha", version="1.0.0", group_id="g1", cleaning_job_id="c1"))
    assert waiting.value.status_code == 409
    _complete()
    rnd = training_round_service.create_round(TrainingRoundCreate(
        model_name="alpha", version="1.0.0", group_id="g1", cleaning_job_id="c1"))

    assert training_round_service.get_round(rnd.round_id).cleaning_job_id == "c1"
    snapshot = training_round_service.get_round(rnd.round_id).cleaning_snapshot
    assert snapshot["silo-1"]["output_hash"] == "c" * 64
    from services.cleaning_execution import reschedule
    reschedule("c1", "2099-01-01T00:00:00+00:00")
    assert training_round_service.get_round(rnd.round_id).cleaning_snapshot == snapshot
    with pytest.raises(HTTPException) as pending:
        training_round_service.create_round(TrainingRoundCreate(
            model_name="alpha", version="1.0.0", group_id="g1", cleaning_job_id="c1"))
    assert pending.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        training_round_service.create_round(TrainingRoundCreate(
            model_name="alpha", version="1.0.0", group_id="g1", cleaning_job_id="ghost"))
    assert exc.value.status_code == 404


@pytest.mark.unit
def test_training_job_passes_cleaning_job_id_to_rounds():
    job = training_job_service.create_job(TrainingJobRequest(
        job_id="t1", model_name="alpha", version="1.0.0", group_id="g1",
        cleaning_job_id="c1", max_rounds=1))
    assert job.cleaning_job_id == "c1"
    assert training_job_service.tick() == []
    assert training_round_service.list_rounds() == []
    assert training_job_service.get_job("t1").rounds_failed == 0
    _complete()
    assert training_job_service.tick() == ["t1"]
    round_id = training_job_service.get_job("t1").current_round_id
    assert training_round_service.get_round(round_id).cleaning_job_id == "c1"

    with pytest.raises(HTTPException) as exc:
        training_job_service.create_job(TrainingJobRequest(
            job_id="t2", model_name="alpha", version="1.0.0", group_id="g1",
            cleaning_job_id="ghost"))
    assert exc.value.status_code == 404


@pytest.mark.unit
def test_rounds_without_cleaning_job_stay_unlinked():
    rnd = training_round_service.create_round(TrainingRoundCreate(
        model_name="alpha", version="1.0.0", group_id="g1"))
    assert rnd.cleaning_job_id is None


@pytest.mark.unit
def test_assigned_shards_lists_only_my_shards_by_status():
    mine = cleaning_job_service.list_assigned_shards("silo-2", status="pending")

    assert [(s.job_id, s.shard_index, s.recipe_name, s.recipe_version) for s in mine] == [
        ("c1", 1, "r", "1.0.0")]
    cleaning_job_service.start_shard("c1", 1, "silo-2")
    assert cleaning_job_service.list_assigned_shards("silo-2", status="pending") == []
    running = cleaning_job_service.list_assigned_shards("silo-2", status="running")
    assert [s.status for s in running] == ["running"]
    assert [s.job_id for s in cleaning_job_service.list_assigned_shards("silo-3")] == ["c2"]


@pytest.mark.unit
def test_assigned_shards_api():
    from main import app

    body = TestClient(app).get("/api/cleaning-shards",
                               params={"silo_id": "silo-1", "status": "pending"}).json()

    assert [(s["job_id"], s["shard_index"], s["dataset_label"]) for s in body] == [
        ("c1", 0, "silo-sources")]
