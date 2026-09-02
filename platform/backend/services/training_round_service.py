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
    group = silo_group_service.get_group(request.group_id)

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
        # open 시점 멤버를 동결 — 라운드 도중 그룹이 바뀌어도 진행 중 라운드는 무영향
        member_snapshot=list(group.member_node_ids),
    )
    # 라운드 파일의 모든 쓰기는 _round_lock으로 직렬화한다 — 잠금 없이 쓰면
    # 동시 기여/집계의 load→save 와 read-modify-write 경합으로 방금 만든 라운드가
    # 유실된다 (실측: 250라운드 연속 실행 중 기여 404)
    with _round_lock:
        _save_round(entry)
    logger.info("학습 라운드 생성: %s (%s@%s, group=%s)",
                entry.round_id, request.model_name, request.version, request.group_id)
    return entry


def _verify_membership(round_entry: TrainingRound, silo_id: str) -> None:
    """라운드 open 시점의 멤버 스냅샷과 대조한다 (HFL 설계 스펙 §4.2).

    스냅샷이 `None`이면 스냅샷 도입 이전에 생성된 레코드이므로 현재 그룹 멤버십으로
    폴백한다 — 진행 중이던 기존 라운드의 하위 호환.
    빈 목록 `[]`은 "멤버 0명인 그룹의 스냅샷"이라는 유효한 상태이므로 폴백하지 않는다
    (폴백하면 라운드 도중 추가된 노드가 기여할 수 있어 스냅샷 규칙이 무효가 된다).
    """
    allowed = round_entry.member_snapshot
    if allowed is None:
        allowed = silo_group_service.get_group(round_entry.group_id).member_node_ids
    if silo_id not in allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                f"사일로 '{silo_id}'는 라운드 '{round_entry.round_id}'의 "
                f"참여 스냅샷(그룹 '{round_entry.group_id}')에 없습니다"
            ),
        )


def _verify_aggregated_from(silo_id: str, aggregated_from: list[str]) -> None:
    """대리 제출 출처 검증 (HFL 설계 스펙 §4.2).

    ① 제출자가 해당 클러스터의 집계자인가 → 아니면 403
    ② 하위 목록에 중복이 없는가 → 있으면 422 (리니지 정확도)
    ③ 하위 목록이 클러스터 멤버의 부분집합인가 → 아니면 422
       (집계자는 자기 클러스터의 멤버가 될 수 없으므로 자기 자신 포함도 여기서 422)
    """
    if not aggregated_from:
        return  # 평면 제출 — 기존 경로와 완전히 동일

    cluster = silo_group_service.get_cluster_by_aggregator(silo_id)
    if cluster is None:
        raise HTTPException(
            status_code=403,
            detail=f"사일로 '{silo_id}'는 어떤 클러스터의 집계자도 아니므로 대리 제출할 수 없습니다",
        )

    duplicated = sorted({n for n in aggregated_from if aggregated_from.count(n) > 1})
    if duplicated:
        raise HTTPException(
            status_code=422,
            detail=f"aggregated_from에 중복된 하위 노드: {duplicated}",
        )

    outside = [n for n in aggregated_from if n not in cluster.member_node_ids]
    if outside:
        raise HTTPException(
            status_code=422,
            detail=f"클러스터 '{cluster.group_id}'의 멤버가 아닌 하위 노드: {outside}",
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
        _verify_aggregated_from(contribution.silo_id, contribution.aggregated_from)

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
            "aggregated_from": list(contribution.aggregated_from),
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
        "기여 등록: round=%s silo=%s samples=%d dim=%d aggregated_from=%d",
        contribution.round_id,
        contribution.silo_id,
        contribution.sample_count,
        len(contribution.parameters),
        len(contribution.aggregated_from),
    )
    return ParameterContributionRecord(
        round_id=contribution.round_id,
        silo_id=contribution.silo_id,
        sample_count=contribution.sample_count,
        parameter_dim=len(contribution.parameters),
        submitted_at=record["submitted_at"],
        checksum=record["checksum"],
        aggregated_from=list(contribution.aggregated_from),
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
            aggregated_from=list(r.get("aggregated_from", [])),
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
