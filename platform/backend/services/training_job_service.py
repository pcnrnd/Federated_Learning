"""학습 잡(Training Job) 서비스 — 라운드 자동 연쇄/주기 트리거.

스케줄 종류:
  * manual   — 자동 진행 없음
  * chain    — 이전 라운드 완료 직후 다음 라운드 자동 open
  * interval — 이전 라운드 완료 후 interval_seconds 경과 시 다음 라운드 open
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import HTTPException

from config.federated_manager import load_training_jobs, save_training_jobs
from models.federated_schemas import (
    TrainingJob,
    TrainingJobRequest,
    TrainingRoundCreate,
)
from services import resource_service, silo_group_service, training_round_service
from services.model_registry import get_model

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT_ROUNDS = 3
_job_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _update_job(
    job_id: str, mutate: Callable[[TrainingJob], TrainingJob | None]
) -> TrainingJob:
    """_job_lock 안에서 잡을 재조회 → 검사·변경 → 저장 (read-check-write).

    잡 파일의 모든 쓰기는 이 함수를 지나야 한다. 잠금 밖 스냅샷(tick)으로 만든
    복사본을 그대로 저장하면 그 사이 들어온 cancel/pause가 덮어써져 유실된다 —
    mutate는 항상 최신 잡을 받고, None을 반환하면 저장하지 않는다.
    """
    with _job_lock:
        jobs = load_training_jobs()
        if job_id not in jobs:
            raise HTTPException(status_code=404, detail=f"잡 '{job_id}'을 찾을 수 없습니다")
        current = TrainingJob(**jobs[job_id])
        updated = mutate(current)
        if updated is None:
            return current
        jobs[job_id] = updated.model_dump()
        save_training_jobs(jobs)
        return updated


def list_jobs(*, status: str | None = None) -> list[TrainingJob]:
    raw = load_training_jobs()
    jobs = [TrainingJob(**v) for v in raw.values()]
    if status:
        jobs = [j for j in jobs if j.status == status]
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    return jobs


def get_job(job_id: str) -> TrainingJob:
    raw = load_training_jobs()
    if job_id not in raw:
        raise HTTPException(status_code=404, detail=f"잡 '{job_id}'을 찾을 수 없습니다")
    return TrainingJob(**raw[job_id])


def create_job(request: TrainingJobRequest) -> TrainingJob:
    if request.schedule_kind == "interval" and request.interval_seconds <= 0:
        raise HTTPException(
            status_code=400,
            detail="interval 스케줄은 interval_seconds > 0 이어야 합니다",
        )
    # 모델·그룹 사전 검증
    get_model(request.model_name, request.version)
    silo_group_service.get_group(request.group_id)

    now = _now_iso()
    job = TrainingJob(
        job_id=request.job_id,
        model_name=request.model_name,
        version=request.version,
        group_id=request.group_id,
        schedule_kind=request.schedule_kind,
        interval_seconds=request.interval_seconds,
        min_contributions=request.min_contributions,
        max_rounds=request.max_rounds,
        status="active",
        rounds_completed=0,
        rounds_failed=0,
        current_round_id=None,
        last_round_completed_at=None,
        created_at=now,
        updated_at=now,
        notes=request.notes,
    )
    # 중복 ID 검사와 저장을 같은 잠금 구간에서 — 동시 생성 요청이 서로를 덮어쓰지 않는다
    with _job_lock:
        jobs = load_training_jobs()
        if request.job_id in jobs:
            raise HTTPException(status_code=409, detail=f"잡 '{request.job_id}'은 이미 존재합니다")
        jobs[job.job_id] = job.model_dump()
        save_training_jobs(jobs)
    logger.info("잡 생성: %s (schedule=%s, max_rounds=%d)",
                request.job_id, request.schedule_kind, request.max_rounds)
    return job


def _transition(
    job_id: str, status: str, *, allowed_from: tuple[str, ...], reject_detail: str
) -> TrainingJob:
    """상태 전이 — 선행조건 검사와 저장을 같은 잠금 구간에서 수행한다."""

    def mutate(job: TrainingJob) -> TrainingJob:
        if job.status not in allowed_from:
            raise HTTPException(status_code=409, detail=reject_detail.format(status=job.status))
        return job.model_copy(update={"status": status, "updated_at": _now_iso()})

    return _update_job(job_id, mutate)


def pause_job(job_id: str) -> TrainingJob:
    return _transition(
        job_id, "paused", allowed_from=("active",),
        reject_detail="상태가 '{status}'인 잡은 일시정지할 수 없습니다",
    )


def resume_job(job_id: str) -> TrainingJob:
    return _transition(
        job_id, "active", allowed_from=("paused",),
        reject_detail="상태가 '{status}'인 잡은 재개할 수 없습니다",
    )


def cancel_job(job_id: str) -> TrainingJob:
    return _transition(
        job_id, "cancelled", allowed_from=("active", "paused"),
        reject_detail="이미 종료된 잡입니다 (status={status})",
    )


def _open_round_for_job(job_id: str) -> tuple[TrainingJob, bool]:
    """잠금 안에서 잡을 재조회해 여전히 active·라운드 없음일 때만 라운드를 연다.

    Returns: (최신 잡, 이번 호출에서 라운드를 열었는지)
    tick 스냅샷과 실제 open 사이에 cancel/pause가 끼어들면 (스냅샷은 active였어도)
    라운드를 만들지 않는다 — create_round 부수효과까지 잠금 구간에 포함한다.
    """
    opened = False

    def mutate(job: TrainingJob) -> TrainingJob | None:
        nonlocal opened
        if job.status != "active" or job.current_round_id is not None:
            return None
        new_round = training_round_service.create_round(
            TrainingRoundCreate(
                model_name=job.model_name,
                version=job.version,
                group_id=job.group_id,
                min_contributions=job.min_contributions,
                notes=f"auto from job={job.job_id}",
            )
        )
        opened = True
        logger.info("잡 %s: 새 라운드 %s open", job.job_id, new_round.round_id)
        return job.model_copy(
            update={"current_round_id": new_round.round_id, "updated_at": _now_iso()}
        )

    return _update_job(job_id, mutate), opened


def _is_due(job: TrainingJob) -> bool:
    """현재 라운드가 없거나 종료된 상태에서 다음 라운드를 열 시점인지 판단"""
    if job.schedule_kind == "manual":
        return False
    if job.last_round_completed_at is None:
        # 첫 라운드는 항상 즉시 due (active 상태 가정)
        return True
    if job.schedule_kind == "chain":
        return True
    # interval
    last = datetime.fromisoformat(job.last_round_completed_at)
    elapsed = (_now() - last).total_seconds()
    return elapsed >= job.interval_seconds


def _reconcile_current_round(job: TrainingJob) -> TrainingJob:
    """현재 라운드 상태를 점검해 잡 카운터를 업데이트한다.

    카운터 반영은 잠금 안의 최신 잡에 적용한다 — 스냅샷 시점 이후 cancel된 잡의
    status를 스냅샷 값(active)으로 되돌리지 않는다.
    """
    round_id = job.current_round_id
    if round_id is None:
        return job
    try:
        rnd = training_round_service.get_round(round_id)
    except HTTPException:
        rnd = None  # 라운드가 외부에서 삭제된 경우 — 카운터 변경 없이 current_round_id만 비움

    def mutate(fresh: TrainingJob) -> TrainingJob | None:
        if fresh.current_round_id != round_id:
            return None  # 다른 tick이 이미 반영함
        if rnd is None:
            return fresh.model_copy(update={"current_round_id": None, "updated_at": _now_iso()})
        if rnd.status == "completed":
            return fresh.model_copy(
                update={
                    "rounds_completed": fresh.rounds_completed + 1,
                    "current_round_id": None,
                    "last_round_completed_at": rnd.aggregated_at or _now_iso(),
                    "updated_at": _now_iso(),
                }
            )
        if rnd.status == "failed":
            return fresh.model_copy(
                update={
                    "rounds_failed": fresh.rounds_failed + 1,
                    "current_round_id": None,
                    "updated_at": _now_iso(),
                    "error": rnd.error,
                }
            )
        return None

    return _update_job(job.job_id, mutate)


def _maybe_complete(job: TrainingJob) -> TrainingJob:
    def mutate(fresh: TrainingJob) -> TrainingJob | None:
        if (
            fresh.status == "active"
            and fresh.rounds_completed >= fresh.max_rounds
            and fresh.current_round_id is None
        ):
            logger.info("잡 %s 완료 (rounds_completed=%d)", fresh.job_id, fresh.rounds_completed)
            return fresh.model_copy(update={"status": "completed", "updated_at": _now_iso()})
        return None

    return _update_job(job.job_id, mutate)


def tick(max_concurrent_rounds: int = DEFAULT_MAX_CONCURRENT_ROUNDS) -> list[str]:
    """잡 스케줄러 단일 tick.

    Returns: 이 tick에서 새로 라운드를 연 잡 ID 목록
    """
    triggered: list[str] = []
    with _job_lock:
        active_jobs = [j for j in list_jobs() if j.status == "active"]

    # 현재 진행 중인 모든 라운드 수 = 동시성 게이트
    open_rounds = training_round_service.list_rounds(status="open")
    aggregating_rounds = training_round_service.list_rounds(status="aggregating")
    capacity = max_concurrent_rounds - len(open_rounds) - len(aggregating_rounds)

    for job in active_jobs:
        job = _reconcile_current_round(job)
        job = _maybe_complete(job)
        if job.status != "active":
            continue
        if job.current_round_id is not None:
            continue  # 라운드 진행 중
        if job.rounds_completed + job.rounds_failed >= job.max_rounds:
            _maybe_complete(job)
            continue
        if not _is_due(job):
            continue
        # 자원 게이트 — 그룹 멤버 중 한 노드라도 임계값 초과면 다음 라운드 보류
        try:
            group = silo_group_service.get_group(job.group_id)
            if resource_service.group_has_pressure(group.member_node_ids):
                logger.info("잡 %s 자원 압박으로 보류 (group=%s)", job.job_id, job.group_id)
                continue
        except HTTPException:
            pass
        if capacity <= 0:
            break
        try:
            _, opened = _open_round_for_job(job.job_id)
        except HTTPException as exc:
            logger.warning("잡 %s 라운드 생성 실패: %s", job.job_id, exc.detail)
            detail = str(exc.detail)
            _update_job(
                job.job_id,
                lambda fresh: fresh.model_copy(
                    update={
                        "rounds_failed": fresh.rounds_failed + 1,
                        "updated_at": _now_iso(),
                        "error": detail,
                    }
                ),
            )
            continue
        if opened:
            triggered.append(job.job_id)
            capacity -= 1
    return triggered
