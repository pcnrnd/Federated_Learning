"""학습 라운드 + 파라미터 수집 통합 테스트"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from config.server_manager import save_servers
from models.federated_schemas import (
    ParameterContribution,
    SiloGroupRequest,
    TrainingRoundCreate,
)
from models.packaging_schemas import ModelRegisterRequest
from services import (
    model_registry,
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
        SiloGroupRequest(
            group_id="g1",
            description="test",
            member_node_ids=["silo-1", "silo-2"],
        )
    )


def _create_round(min_contrib: int = 2):
    return training_round_service.create_round(
        TrainingRoundCreate(
            model_name="alpha",
            version="1.0.0",
            group_id="g1",
            min_contributions=min_contrib,
        )
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


@pytest.mark.unit
def test_create_round_validates_model_and_group():
    with pytest.raises(HTTPException) as exc:
        training_round_service.create_round(
            TrainingRoundCreate(
                model_name="ghost",
                version="1.0.0",
                group_id="g1",
            )
        )
    assert exc.value.status_code == 404


@pytest.mark.unit
def test_create_round_validates_group():
    with pytest.raises(HTTPException) as exc:
        training_round_service.create_round(
            TrainingRoundCreate(
                model_name="alpha",
                version="1.0.0",
                group_id="missing",
            )
        )
    assert exc.value.status_code == 404


@pytest.mark.unit
def test_contribution_must_be_group_member():
    rnd = _create_round()
    with pytest.raises(HTTPException) as exc:
        _contribute(rnd.round_id, "silo-99", 10, [1.0])
    assert exc.value.status_code == 403


@pytest.mark.unit
def test_duplicate_contribution_rejected():
    rnd = _create_round()
    _contribute(rnd.round_id, "silo-1", 10, [1.0])
    with pytest.raises(HTTPException) as exc:
        _contribute(rnd.round_id, "silo-1", 10, [1.0])
    assert exc.value.status_code == 409


@pytest.mark.unit
def test_aggregate_below_min_contrib_returns_400():
    rnd = _create_round(min_contrib=2)
    _contribute(rnd.round_id, "silo-1", 10, [1.0])
    with pytest.raises(HTTPException) as exc:
        training_round_service.aggregate_round(rnd.round_id)
    assert exc.value.status_code == 400


@pytest.mark.unit
def test_full_round_lifecycle_aggregates_weighted_fedavg():
    rnd = _create_round(min_contrib=2)
    _contribute(rnd.round_id, "silo-1", 90, [10.0, 10.0])
    _contribute(rnd.round_id, "silo-2", 10, [0.0, 0.0])

    result = training_round_service.aggregate_round(rnd.round_id)

    assert result.contributor_count == 2
    assert result.total_samples == 100
    assert result.parameter_dim == 2
    assert result.parameters[0] == pytest.approx(9.0)
    assert result.parameters[1] == pytest.approx(9.0)

    completed = training_round_service.get_round(rnd.round_id)
    assert completed.status == "completed"
    assert completed.aggregated_at is not None


@pytest.mark.unit
def test_contribution_after_completion_rejected():
    rnd = _create_round(min_contrib=2)
    _contribute(rnd.round_id, "silo-1", 1, [1.0])
    _contribute(rnd.round_id, "silo-2", 1, [3.0])
    training_round_service.aggregate_round(rnd.round_id)

    with pytest.raises(HTTPException) as exc:
        training_round_service.submit_contribution(
            ParameterContribution(
                round_id=rnd.round_id,
                silo_id="silo-1",
                sample_count=1,
                parameters=[1.0],
            )
        )
    assert exc.value.status_code in (409, 403)  # 상태 또는 그룹 검증
