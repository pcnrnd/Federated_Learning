"""Batch Scheduling 자동화 — TrainingJob 서비스 테스트"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from config.server_manager import save_servers
from models.federated_schemas import (
    ParameterContribution,
    SiloGroupRequest,
    TrainingJobRequest,
)
from models.packaging_schemas import ModelRegisterRequest
from services import (
    model_registry,
    silo_group_service,
    training_job_service,
    training_round_service,
)


@pytest.fixture(autouse=True)
def _seed(tmp_path):
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
    weights = tmp_path / "m.pt"
    weights.write_bytes(b"")
    model_registry.register_model(
        ModelRegisterRequest(
            name="alpha",
            version="1.0.0",
            framework="pytorch",
            weights_path=str(weights),
        )
    )
    silo_group_service.create_group(
        SiloGroupRequest(group_id="g1", member_node_ids=["silo-1", "silo-2"])
    )


def _contribute(round_id: str, silo_id: str, samples: int, params: list[float]):
    return training_round_service.submit_contribution(
        ParameterContribution(
            round_id=round_id,
            silo_id=silo_id,
            sample_count=samples,
            parameters=params,
        )
    )


def _job(
    job_id: str = "j1",
    schedule: str = "chain",
    interval: int = 0,
    max_rounds: int = 3,
) -> TrainingJobRequest:
    return TrainingJobRequest(
        job_id=job_id,
        model_name="alpha",
        version="1.0.0",
        group_id="g1",
        schedule_kind=schedule,
        interval_seconds=interval,
        min_contributions=2,
        max_rounds=max_rounds,
    )


@pytest.mark.unit
def test_create_job_validates_model_and_group():
    with pytest.raises(HTTPException) as exc:
        training_job_service.create_job(
            TrainingJobRequest(
                job_id="bad",
                model_name="ghost",
                version="1.0.0",
                group_id="g1",
                schedule_kind="chain",
                max_rounds=1,
            )
        )
    assert exc.value.status_code == 404


@pytest.mark.unit
def test_interval_job_requires_positive_interval():
    with pytest.raises(HTTPException) as exc:
        training_job_service.create_job(_job(schedule="interval", interval=0))
    assert exc.value.status_code == 400


@pytest.mark.unit
def test_first_tick_opens_initial_round_for_active_job():
    training_job_service.create_job(_job())

    triggered = training_job_service.tick()

    assert triggered == ["j1"]
    job = training_job_service.get_job("j1")
    assert job.current_round_id is not None
    assert training_round_service.get_round(job.current_round_id).status == "open"


@pytest.mark.unit
def test_manual_schedule_does_not_advance_after_completion():
    training_job_service.create_job(_job(schedule="manual"))
    triggered = training_job_service.tick()
    # manual: 첫 라운드도 자동으로 열지 않음
    assert triggered == []
    job = training_job_service.get_job("j1")
    assert job.current_round_id is None


@pytest.mark.unit
def test_chain_advances_to_next_round_after_completion():
    training_job_service.create_job(_job(max_rounds=2))
    # 첫 tick — 라운드 1 open
    training_job_service.tick()
    job = training_job_service.get_job("j1")
    rnd_id_1 = job.current_round_id
    assert rnd_id_1 is not None

    # 라운드 1 기여 + 집계
    _contribute(rnd_id_1, "silo-1", 1, [1.0])
    _contribute(rnd_id_1, "silo-2", 1, [3.0])
    training_round_service.aggregate_round(rnd_id_1)

    # 두 번째 tick — reconcile 후 라운드 2 open
    triggered = training_job_service.tick()
    assert triggered == ["j1"]
    job = training_job_service.get_job("j1")
    assert job.rounds_completed == 1
    assert job.current_round_id is not None
    assert job.current_round_id != rnd_id_1


@pytest.mark.unit
def test_job_completes_when_max_rounds_reached():
    training_job_service.create_job(_job(max_rounds=1))
    training_job_service.tick()
    job = training_job_service.get_job("j1")
    rnd_id = job.current_round_id

    _contribute(rnd_id, "silo-1", 1, [1.0])
    _contribute(rnd_id, "silo-2", 1, [3.0])
    training_round_service.aggregate_round(rnd_id)

    training_job_service.tick()  # reconcile + complete

    job = training_job_service.get_job("j1")
    assert job.status == "completed"
    assert job.rounds_completed == 1
    assert job.current_round_id is None


@pytest.mark.unit
def test_paused_job_does_not_advance():
    training_job_service.create_job(_job())
    training_job_service.pause_job("j1")

    triggered = training_job_service.tick()

    assert triggered == []
    assert training_job_service.get_job("j1").current_round_id is None


@pytest.mark.unit
def test_resume_reactivates_advancement():
    training_job_service.create_job(_job())
    training_job_service.pause_job("j1")
    training_job_service.tick()  # 아무것도 안 일어남
    training_job_service.resume_job("j1")

    triggered = training_job_service.tick()

    assert triggered == ["j1"]


@pytest.mark.unit
def test_cancel_job_blocks_further_ticks():
    training_job_service.create_job(_job())
    training_job_service.cancel_job("j1")

    assert training_job_service.tick() == []


@pytest.mark.unit
def test_interval_schedule_respects_elapsed_time():
    training_job_service.create_job(_job(schedule="interval", interval=60, max_rounds=2))
    # 첫 라운드 (last_round_completed_at=None → 즉시 due)
    training_job_service.tick()
    job = training_job_service.get_job("j1")
    rnd_id = job.current_round_id

    _contribute(rnd_id, "silo-1", 1, [1.0])
    _contribute(rnd_id, "silo-2", 1, [3.0])
    training_round_service.aggregate_round(rnd_id)
    training_job_service.tick()  # reconcile만, 즉시 다음 라운드는 X

    job_after = training_job_service.get_job("j1")
    assert job_after.rounds_completed == 1
    # 60초 경과 전이라 다음 라운드 미생성
    assert job_after.current_round_id is None

    # 시간을 60초+ 과거로 백데이트해서 due 충족 검증
    backdated = (
        datetime.now(timezone.utc) - timedelta(seconds=61)
    ).isoformat()
    from config.federated_manager import load_training_jobs, save_training_jobs

    jobs = load_training_jobs()
    jobs["j1"]["last_round_completed_at"] = backdated
    save_training_jobs(jobs)

    triggered = training_job_service.tick()
    assert triggered == ["j1"]


@pytest.mark.unit
def test_concurrent_rounds_capacity_limits_tick():
    # 동시 라운드 한도 1 — 첫 잡만 라운드 열고 둘째 잡은 대기
    training_job_service.create_job(_job(job_id="a"))
    training_job_service.create_job(_job(job_id="b"))

    triggered = training_job_service.tick(max_concurrent_rounds=1)

    assert len(triggered) == 1
    assert triggered[0] in {"a", "b"}
