"""주기 수집 스케줄러 테스트"""
from __future__ import annotations

import pytest

from config.server_manager import save_servers
from models.federated_schemas import (
    ParameterContribution,
    SiloGroupRequest,
    TrainingRoundCreate,
)
from models.packaging_schemas import ModelRegisterRequest
from services import (
    model_registry,
    round_scheduler,
    silo_group_service,
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tick_aggregates_open_rounds_with_enough_contributions():
    rnd_full = training_round_service.create_round(
        TrainingRoundCreate(
            model_name="alpha", version="1.0.0", group_id="g1", min_contributions=2
        )
    )
    rnd_partial = training_round_service.create_round(
        TrainingRoundCreate(
            model_name="alpha", version="1.0.0", group_id="g1", min_contributions=2
        )
    )
    training_round_service.submit_contribution(
        ParameterContribution(
            round_id=rnd_full.round_id, silo_id="silo-1", sample_count=1, parameters=[1.0]
        )
    )
    training_round_service.submit_contribution(
        ParameterContribution(
            round_id=rnd_full.round_id, silo_id="silo-2", sample_count=1, parameters=[3.0]
        )
    )
    training_round_service.submit_contribution(
        ParameterContribution(
            round_id=rnd_partial.round_id, silo_id="silo-1", sample_count=1, parameters=[1.0]
        )
    )

    scheduler = round_scheduler.RoundScheduler(interval_seconds=1.0)
    aggregated_ids = await scheduler.tick()

    assert rnd_full.round_id in aggregated_ids
    assert rnd_partial.round_id not in aggregated_ids
    assert training_round_service.get_round(rnd_full.round_id).status == "completed"
    assert training_round_service.get_round(rnd_partial.round_id).status == "open"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tick_idempotent_on_empty_state():
    scheduler = round_scheduler.RoundScheduler(interval_seconds=1.0)
    result = await scheduler.tick()
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scheduler_start_stop_lifecycle():
    scheduler = round_scheduler.RoundScheduler(interval_seconds=1.0)
    assert scheduler.running is False
    await scheduler.start()
    assert scheduler.running is True
    await scheduler.stop()
    assert scheduler.running is False
