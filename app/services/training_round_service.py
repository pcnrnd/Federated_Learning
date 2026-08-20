"""학습 라운드 + 파라미터 수집 서비스"""
from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from config.federated_manager import (
    load_contributions,
    load_training_rounds,
    save_contributions,
    save_training_rounds,
)
from models.federated_schemas import (
    AggregateResult,
    ParameterContribution,
    ParameterContributionRecord,
    TrainingRound,
    TrainingRoundCreate,
)
from services import fedavg_aggregator, silo_group_service
from services.model_registry import get_model

logger = logging.getLogger(__name__)

_round_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_round(entry: TrainingRound) -> None:
    rounds = load_training_rounds()
    rounds[entry.round_id] = entry.model_dump()
    save_training_rounds(rounds)


def list_rounds(
    *,
    model_name: str | None = None,
    group_id: str | None = None,
    status: str | None = None,
) -> list[TrainingRound]:
    raw = load_training_rounds()
    rounds = [TrainingRound(**v) for v in raw.values()]
    if model_name:
        rounds = [r for r in rounds if r.model_name == model_name]
    if group_id:
        rounds = [r for r in rounds if r.group_id == group_id]
    if status:
        rounds = [r for r in rounds if r.status == status]
    rounds.sort(key=lambda r: r.created_at, reverse=True)
    return rounds


def get_round(round_id: str) -> TrainingRound:
    raw = load_training_rounds()
    if round_id not in raw:
        raise HTTPException(status_code=404, detail="학습 라운드를 찾을 수 없습니다")
    return TrainingRound(**raw[round_id])


def create_round(request: TrainingRoundCreate) -> TrainingRound:
    """학습 라운드 생성 — 모델/그룹 존재 사전 검증"""
    get_model(request.model_name, request.version)
    silo_group_service.get_group(request.group_id)

    entry = TrainingRound(
        round_id=uuid.uuid4().hex,
        model_name=request.model_name,
        version=request.version,
        group_id=request.group_id,
        min_contributions=request.min_contributions,
        status="open",
        contributors=[],
        total_samples=0,
        created_at=_now_iso(),
        notes=request.notes,
    )
    _save_round(entry)
    logger.info("학습 라운드 생성: %s (%s@%s, group=%s)",
                entry.round_id, request.model_name, request.version, request.group_id)
    return entry


def _verify_membership(round_entry: TrainingRound, silo_id: str) -> None:
    group = silo_group_service.get_group(round_entry.group_id)
    if silo_id not in group.member_node_ids:
        raise HTTPException(
            status_code=403,
            detail=f"사일로 '{silo_id}'는 그룹 '{group.group_id}'의 멤버가 아닙니다",
        )


def _checksum_params(parameters: list[float]) -> str:
    raw = ",".join(f"{v:.10g}" for v in parameters).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def submit_contribution(contribution: ParameterContribution) -> ParameterContributionRecord:
    """사일로의 파라미터 기여를 라운드에 등록한다."""
    with _round_lock:
        entry = get_round(contribution.round_id)
        if entry.status != "open":
            raise HTTPException(
                status_code=409,
                detail=f"라운드 상태가 '{entry.status}'이므로 기여를 받을 수 없습니다",
            )
        _verify_membership(entry, contribution.silo_id)

        contributions = load_contributions()
        round_bucket = contributions.setdefault(contribution.round_id, {})
        if contribution.silo_id in round_bucket:
            raise HTTPException(
                status_code=409,
                detail=f"사일로 '{contribution.silo_id}'는 이미 기여하였습니다",
            )

        record = {
            "silo_id": contribution.silo_id,
            "sample_count": contribution.sample_count,
            "parameters": list(contribution.parameters),
            "submitted_at": _now_iso(),
            "checksum": contribution.checksum or _checksum_params(contribution.parameters),
        }
        round_bucket[contribution.silo_id] = record
        save_contributions(contributions)

        updated = entry.model_copy(
            update={
                "contributors": entry.contributors + [contribution.silo_id],
                "total_samples": entry.total_samples + contribution.sample_count,
            }
        )
        _save_round(updated)

    logger.info(
        "기여 등록: round=%s silo=%s samples=%d dim=%d",
        contribution.round_id,
        contribution.silo_id,
        contribution.sample_count,
        len(contribution.parameters),
    )
    return ParameterContributionRecord(
        round_id=contribution.round_id,
        silo_id=contribution.silo_id,
        sample_count=contribution.sample_count,
        parameter_dim=len(contribution.parameters),
        submitted_at=record["submitted_at"],
        checksum=record["checksum"],
    )


def list_contributions(round_id: str) -> list[ParameterContributionRecord]:
    contributions = load_contributions().get(round_id, {})
    records = [
        ParameterContributionRecord(
            round_id=round_id,
            silo_id=r["silo_id"],
            sample_count=r["sample_count"],
            parameter_dim=len(r["parameters"]),
            submitted_at=r["submitted_at"],
            checksum=r.get("checksum"),
        )
        for r in contributions.values()
    ]
    records.sort(key=lambda r: r.submitted_at)
    return records


def aggregate_round(round_id: str) -> AggregateResult:
    """라운드의 기여들을 FedAvg로 집계해 글로벌 파라미터를 산출한다."""
    with _round_lock:
        entry = get_round(round_id)
        if entry.status == "completed":
            raise HTTPException(status_code=409, detail="이미 집계 완료된 라운드입니다")
        contributions = load_contributions().get(round_id, {})
        if len(contributions) < entry.min_contributions:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"기여수 부족: 현재 {len(contributions)} < "
                    f"min_contributions {entry.min_contributions}"
                ),
            )

        _save_round(entry.model_copy(update={"status": "aggregating"}))

        try:
            payload = [
                (r["silo_id"], r["sample_count"], r["parameters"])
                for r in contributions.values()
            ]
            aggregated, total = fedavg_aggregator.aggregate(payload)
        except ValueError as exc:
            _save_round(entry.model_copy(update={"status": "failed", "error": str(exc)}))
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        completed_at = _now_iso()
        completed = entry.model_copy(
            update={
                "status": "completed",
                "aggregated_parameter_dim": len(aggregated),
                "aggregated_at": completed_at,
                "total_samples": total,
            }
        )
        _save_round(completed)

    logger.info(
        "라운드 집계 완료: %s dim=%d contributors=%d total_samples=%d",
        round_id,
        len(aggregated),
        len(contributions),
        total,
    )
    return AggregateResult(
        round_id=round_id,
        parameter_dim=len(aggregated),
        parameters=aggregated,
        total_samples=total,
        contributor_count=len(contributions),
        aggregated_at=completed_at,
    )
