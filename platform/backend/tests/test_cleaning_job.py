"""정제 잡 오케스트레이션 테스트"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from config.server_manager import save_servers
from models.cleaning_schemas import (
    CleaningJobCreate,
    CleaningRecipeRequest,
    CleaningStep,
    ShardReport,
)
from models.federated_schemas import SiloGroupRequest
from services import (
    cleaning_job_service,
    cleaning_recipe_service,
    silo_group_service,
)


@pytest.fixture(autouse=True)
def _seed():
    save_servers(
        {
            "silo-1": {
                "base_url": "tcp://localhost:2371",
                "label": "silo-1",
                "type": "remote",
                "role": "client",
                "tls": False,
            },
            "silo-2": {
                "base_url": "tcp://localhost:2372",
                "label": "silo-2",
                "type": "remote",
                "role": "client",
                "tls": False,
            },
        }
    )
    silo_group_service.create_group(
        SiloGroupRequest(group_id="g1", member_node_ids=["silo-1", "silo-2"])
    )
    cleaning_recipe_service.register_recipe(
        CleaningRecipeRequest(
            name="hospital",
            version="1.0.0",
            steps=[CleaningStep(type="drop_nulls", params={"columns": ["age"]})],
        )
    )


def _create_job() -> str:
    job = cleaning_job_service.create_job(
        CleaningJobCreate(
            job_id="j1",
            recipe_name="hospital",
            recipe_version="1.0.0",
            group_id="g1",
            dataset_label="patients_2026",
        )
    )
    return job.job_id


def _report(silo_id: str, shard: int, rows_in: int, rows_out: int) -> ShardReport:
    return ShardReport(
        job_id="j1",
        shard_index=shard,
        silo_id=silo_id,
        rows_in=rows_in,
        rows_out=rows_out,
        step_counters={"drop_nulls": rows_in - rows_out},
        started_at="2026-05-14T00:00:00Z",
        completed_at="2026-05-14T00:01:00Z",
    )


@pytest.mark.unit
def test_create_job_assigns_one_shard_per_member():
    _create_job()
    job = cleaning_job_service.get_job("j1")

    assert len(job.shards) == 2
    assert {s.silo_id for s in job.shards} == {"silo-1", "silo-2"}
    assert {s.shard_index for s in job.shards} == {0, 1}
    assert all(s.status == "pending" for s in job.shards)


@pytest.mark.unit
def test_create_job_requires_existing_recipe():
    with pytest.raises(HTTPException) as exc:
        cleaning_job_service.create_job(
            CleaningJobCreate(
                job_id="j-bad",
                recipe_name="ghost",
                recipe_version="1.0.0",
                group_id="g1",
                dataset_label="x",
            )
        )
    assert exc.value.status_code == 404


@pytest.mark.unit
def test_start_shard_only_by_assigned_silo():
    _create_job()
    with pytest.raises(HTTPException) as exc:
        cleaning_job_service.start_shard("j1", 0, "silo-2")  # 잘못된 사일로
    assert exc.value.status_code == 403


@pytest.mark.unit
def test_report_rejects_rows_out_greater_than_in():
    _create_job()
    with pytest.raises(HTTPException) as exc:
        cleaning_job_service.report_shard(
            ShardReport(
                job_id="j1",
                shard_index=0,
                silo_id="silo-1",
                rows_in=100,
                rows_out=200,
                started_at="2026-05-14T00:00:00Z",
                completed_at="2026-05-14T00:01:00Z",
            )
        )
    assert exc.value.status_code == 400


@pytest.mark.unit
def test_full_job_completes_after_all_shards_report():
    _create_job()
    cleaning_job_service.start_shard("j1", 0, "silo-1")
    cleaning_job_service.start_shard("j1", 1, "silo-2")
    cleaning_job_service.report_shard(_report("silo-1", 0, 1000, 950))
    final = cleaning_job_service.report_shard(_report("silo-2", 1, 800, 700))

    assert final.status == "completed"
    assert final.total_rows_in == 1800
    assert final.total_rows_out == 1650
    assert final.aggregated_counters["drop_nulls"] == 150


@pytest.mark.unit
def test_partial_status_when_one_shard_fails():
    _create_job()
    cleaning_job_service.start_shard("j1", 0, "silo-1")
    cleaning_job_service.start_shard("j1", 1, "silo-2")
    cleaning_job_service.report_shard(_report("silo-1", 0, 100, 90))
    failed_report = _report("silo-2", 1, 100, 100).model_copy(
        update={"error": "disk full"}
    )
    final = cleaning_job_service.report_shard(failed_report)

    assert final.status == "partial"
    assert final.shards[1].status == "failed"
    assert final.shards[1].error == "disk full"
