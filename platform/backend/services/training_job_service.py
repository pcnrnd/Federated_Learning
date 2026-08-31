"""학습 잡(Training Job) 서비스 — 라운드 자동 연쇄/주기 트리거.

스케줄 종류:
  * manual   — 자동 진행 없음
  * chain    — 이전 라운드 완료 직후 다음 라운드 자동 open
  * interval — 이전 라운드 완료 후 interval_seconds 경과 시 다음 라운드 open
"""
from __future__ import annotations

import logging
import threading
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


def _save(job: TrainingJob) -> None:
    jobs = load_training_jobs()
    jobs[job.job_id] = job.model_dump()
    save_training_jobs(jobs)


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
    jobs = load_training_jobs()
    if request.job_id in jobs:
        raise HTTPException(status_code=409, detail=f"잡 '{request.job_id}'은 이미 존재합니다")
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
    _save(job)
    logger.info("잡 생성: %s (schedule=%s, max_rounds=%d)",
                request.job_id, request.schedule_kind, request.max_rounds)
    return job


def _transition(job_id: str, status: str) -> TrainingJob:
    with _job_lock:
        job = get_job(job_id)
        updated = job.model_copy(update={"status": status, "updated_at": _now_iso()})
        _save(updated)
        return updated


def pause_job(job_id: str) -> TrainingJob:
    job = get_job(job_id)
    if job.status not in ("active",):
        raise HTTPException(status_code=409, detail=f"상태가 '{job.status}'인 잡은 일시정지할 수 없습니다")
    return _transition(job_id, "paused")


def resume_job(job_id: str) -> TrainingJob:
    job = get_job(job_id)
    if job.status != "paused":
        raise HTTPException(status_code=409, detail=f"상태가 '{job.status}'인 잡은 재개할 수 없습니다")
    return _transition(job_id, "active")


def cancel_job(job_id: str) -> TrainingJob:
    job = get_job(job_id)
    if job.status in ("completed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"이미 종료된 잡입니다 (status={job.status})")
    return _transition(job_id, "cancelled")


def _open_round_for_job(job: TrainingJob) -> TrainingJob:
    new_round = training_round_service.create_round(
        TrainingRoundCreate(
            model_name=job.model_name,
            version=job.version,
            group_id=job.group_id,
            min_contributions=job.min_contributions,
            notes=f"auto from job={job.job_id}",
        )
    )
    updated = job.model_copy(
        update={
            "current_round_id": new_round.round_id,
            "updated_at": _now_iso(),
        }
    )
    _save(updated)
    logger.info("잡 %s: 새 라운드 %s open", job.job_id, new_round.round_id)
    return updated


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
    """현재 라운드 상태를 점검해 잡 카운터를 업데이트한다."""
    if job.current_round_id is None:
        return job
    try:
        rnd = training_round_service.get_round(job.current_round_id)
    except HTTPException:
        # 라운드가 외부에서 삭제된 경우 — 카운터 변경 없이 current_round_id만 비움
        return job.model_copy(update={"current_round_id": None, "updated_at": _now_iso()})

    if rnd.status == "completed":
        updated = job.model_copy(
            update={
                "rounds_completed": job.rounds_completed + 1,
                "current_round_id": None,
                "last_round_completed_at": rnd.aggregated_at or _now_iso(),
                "updated_at": _now_iso(),
            }
        )
        _save(updated)
        return updated
    if rnd.status == "failed":
        updated = job.model_copy(
            update={
                "rounds_failed": job.rounds_failed + 1,
                "current_round_id": None,
                "updated_at": _now_iso(),
                "error": rnd.error,
            }
        )
        _save(updated)
        return updated
    return job


def _maybe_complete(job: TrainingJob) -> TrainingJob:
    if job.rounds_completed >= job.max_rounds and job.current_round_id is None:
        completed = job.model_copy(update={"status": "completed", "updated_at": _now_iso()})
        _save(completed)
        logger.info("잡 %s 완료 (rounds_completed=%d)", job.job_id, job.rounds_completed)
        return completed
    return job


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
            _open_round_for_job(job)
            triggered.append(job.job_id)
            capacity -= 1
        except HTTPException as exc:
            logger.warning("잡 %s 라운드 생성 실패: %s", job.job_id, exc.detail)
            failed = job.model_copy(
                update={
                    "rounds_failed": job.rounds_failed + 1,
                    "updated_at": _now_iso(),
                    "error": str(exc.detail),
                }
            )
            _save(failed)
    return triggered
