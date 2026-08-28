"""학습 라운드 / 파라미터 수집 API"""
from __future__ import annotations

from fastapi import APIRouter, Query

from models.federated_schemas import (
    AggregateResult,
    ParameterContribution,
    ParameterContributionRecord,
    TrainingRound,
    TrainingRoundCreate,
)
from services import training_round_service

router = APIRouter(prefix="/api/training-rounds", tags=["training-rounds"])


@router.get("", response_model=list[TrainingRound])
def list_rounds_endpoint(
    model_name: str | None = Query(default=None),
    group_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[TrainingRound]:
    return training_round_service.list_rounds(
        model_name=model_name, group_id=group_id, status=status
    )


@router.post("", response_model=TrainingRound, status_code=201)
def create_round_endpoint(request: TrainingRoundCreate) -> TrainingRound:
    return training_round_service.create_round(request)


@router.get("/{round_id}", response_model=TrainingRound)
def get_round_endpoint(round_id: str) -> TrainingRound:
    return training_round_service.get_round(round_id)


@router.post(
    "/{round_id}/contributions",
    response_model=ParameterContributionRecord,
    status_code=202,
)
def submit_contribution_endpoint(
    round_id: str, contribution: ParameterContribution
) -> ParameterContributionRecord:
    if contribution.round_id != round_id:
        # URL과 body의 round_id 불일치 방지
        contribution = contribution.model_copy(update={"round_id": round_id})
    return training_round_service.submit_contribution(contribution)


@router.get(
    "/{round_id}/contributions",
    response_model=list[ParameterContributionRecord],
)
def list_contributions_endpoint(round_id: str) -> list[ParameterContributionRecord]:
    return training_round_service.list_contributions(round_id)


@router.post("/{round_id}/aggregate", response_model=AggregateResult)
def aggregate_round_endpoint(round_id: str) -> AggregateResult:
    return training_round_service.aggregate_round(round_id)
