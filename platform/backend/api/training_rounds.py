"""학습 라운드 / 파라미터 수집 API"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from models.federated_schemas import (
    AggregateResult,
    ParameterContribution,
    ParameterContributionRecord,
    TrainingRound,
    TrainingRoundCreate,
    TrainingExecutionFailure,
)
from services import training_round_service

router = APIRouter(prefix="/api/training-rounds", tags=["training-rounds"])


@router.get("", response_model=list[TrainingRound])
def list_rounds_endpoint(
    model_name: str | None = Query(default=None),
    group_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[TrainingRound]:
    rounds = training_round_service.list_rounds(
        model_name=model_name, group_id=group_id, status=status
    )
    if status == "open":
        # 사일로 워커(train-loop·LiveWorker)는 status=open으로 학습할 라운드를 찾는다. Flower 라운드는
        # 백엔드가 Flower 실행으로 처리하므로 워커에 보이지 않게 한다 (사일로 이미지는 바꾸지 않음).
        rounds = [r for r in rounds if r.engine != "flower"]
    return rounds


def _reject_flower(round_id: str) -> None:
    if training_round_service.get_round(round_id).engine == "flower":
        raise HTTPException(status_code=409, detail="Flower 엔진 라운드는 사일로 기여·오류 보고를 받지 않습니다")


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
        if contribution.origins is not None:
            raise HTTPException(status_code=422, detail="live URL/body round_id 불일치")
        # URL과 body의 round_id 불일치 방지
        contribution = contribution.model_copy(update={"round_id": round_id})
    _reject_flower(round_id)
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


@router.get("/{round_id}/result", response_model=AggregateResult)
def get_result_endpoint(round_id: str) -> AggregateResult:
    return training_round_service.get_result(round_id)


@router.post("/{round_id}/execution-errors", response_model=TrainingRound)
def report_execution_failure_endpoint(round_id: str, failure: TrainingExecutionFailure) -> TrainingRound:
    _reject_flower(round_id)
    return training_round_service.report_execution_failure(round_id, failure)
