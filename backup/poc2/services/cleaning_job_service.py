"""정제 잡 오케스트레이션 — 그룹 멤버에 샤드를 자동 배정하고 결과를 집계.

분산 처리 흐름:
  1. create_job — 그룹 멤버 N개 → 샤드 N개 자동 생성 (1:1 매핑)
  2. start_shard — 사일로가 작업 시작을 알림 (status pending→running)
  3. report_shard — 사일로가 통계 결과를 push (status running→completed/failed)
  4. _maybe_finalize — 모든 샤드가 완료되면 잡 상태 갱신 + 카운터 합산
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from fastapi import HTTPException

from config.cleaning_manager import load_jobs, save_jobs
from models.cleaning_schemas import (
    CleaningJob,
    CleaningJobCreate,
    ShardAssignment,
    ShardReport,
)
from services import cleaning_recipe_service, silo_group_service

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save(job: CleaningJob) -> None:
    jobs = load_jobs()
    jobs[job.job_id] = job.model_dump()
    save_jobs(jobs)


def list_jobs(status: str | None = None) -> list[CleaningJob]:
    raw = load_jobs()
    jobs = [CleaningJob(**v) for v in raw.values()]
    if status:
        jobs = [j for j in jobs if j.status == status]
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    return jobs


def get_job(job_id: str) -> CleaningJob:
    raw = load_jobs()
    if job_id not in raw:
        raise HTTPException(status_code=404, detail=f"잡 '{job_id}' 없음")
    return CleaningJob(**raw[job_id])


def create_job(request: CleaningJobCreate) -> CleaningJob:
    """그룹 멤버 사일로마다 1개 샤드를 자동 배정"""
    jobs = load_jobs()
    if request.job_id in jobs:
        raise HTTPException(status_code=409, detail=f"잡 '{request.job_id}' 중복")

    # 레시피 + 그룹 사전 검증
    cleaning_recipe_service.get_recipe(request.recipe_name, request.recipe_version)
    group = silo_group_service.get_group(request.group_id)
    if not group.member_node_ids:
        raise HTTPException(
            status_code=400, detail=f"그룹 '{group.group_id}'에 멤버가 없습니다"
        )

    shards = [
        ShardAssignment(shard_index=i, silo_id=silo_id, status="pending")
        for i, silo_id in enumerate(group.member_node_ids)
    ]
    now = _now_iso()
    job = CleaningJob(
        job_id=request.job_id,
        recipe_name=request.recipe_name,
        recipe_version=request.recipe_version,
        group_id=request.group_id,
        dataset_label=request.dataset_label,
        status="pending",
        shards=shards,
        created_at=now,
        updated_at=now,
        notes=request.notes,
    )
    _save(job)
    logger.info(
        "정제 잡 생성: %s (recipe=%s@%s, group=%s, shards=%d)",
        request.job_id,
        request.recipe_name,
        request.recipe_version,
        request.group_id,
        len(shards),
    )
    return job


def start_shard(job_id: str, shard_index: int, silo_id: str) -> CleaningJob:
    """사일로가 샤드 작업 시작을 알림"""
    with _lock:
        job = get_job(job_id)
        if shard_index >= len(job.shards):
            raise HTTPException(status_code=400, detail="유효하지 않은 shard_index")
        shard = job.shards[shard_index]
        if shard.silo_id != silo_id:
            raise HTTPException(
                status_code=403,
                detail=f"사일로 '{silo_id}'는 샤드 {shard_index}에 배정되지 않음",
            )
        if shard.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"샤드 상태 '{shard.status}'에서 start 불가",
            )
        updated_shard = shard.model_copy(
            update={"status": "running", "started_at": _now_iso()}
        )
        new_shards = list(job.shards)
        new_shards[shard_index] = updated_shard
        updated_job = job.model_copy(
            update={
                "shards": new_shards,
                "status": "running" if job.status == "pending" else job.status,
                "updated_at": _now_iso(),
            }
        )
        _save(updated_job)
        return updated_job


def report_shard(report: ShardReport) -> CleaningJob:
    """사일로가 샤드 처리 결과를 push (통계만)"""
    if report.rows_out > report.rows_in:
        raise HTTPException(
            status_code=400, detail="rows_out > rows_in 은 불가능합니다"
        )
    with _lock:
        job = get_job(report.job_id)
        if report.shard_index >= len(job.shards):
            raise HTTPException(status_code=400, detail="유효하지 않은 shard_index")
        shard = job.shards[report.shard_index]
        if shard.silo_id != report.silo_id:
            raise HTTPException(
                status_code=403,
                detail=f"사일로 '{report.silo_id}'는 샤드 {report.shard_index}에 배정되지 않음",
            )
        if shard.status not in ("running", "pending"):
            raise HTTPException(
                status_code=409,
                detail=f"샤드 상태 '{shard.status}'에서 report 불가",
            )

        new_status = "failed" if report.error else "completed"
        updated_shard = shard.model_copy(
            update={
                "status": new_status,
                "rows_in": report.rows_in,
                "rows_out": report.rows_out,
                "step_counters": dict(report.step_counters),
                "started_at": shard.started_at or report.started_at,
                "completed_at": report.completed_at,
                "error": report.error,
            }
        )
        new_shards = list(job.shards)
        new_shards[report.shard_index] = updated_shard
        updated_job = job.model_copy(update={"shards": new_shards, "updated_at": _now_iso()})
        _save(updated_job)
        finalized = _maybe_finalize(updated_job)
        return finalized


def _maybe_finalize(job: CleaningJob) -> CleaningJob:
    if any(s.status in ("pending", "running") for s in job.shards):
        return job
    failed = sum(1 for s in job.shards if s.status == "failed")
    completed = sum(1 for s in job.shards if s.status == "completed")
    if failed == len(job.shards):
        new_status = "failed"
    elif failed > 0 and completed > 0:
        new_status = "partial"
    elif failed == 0:
        new_status = "completed"
    else:
        new_status = "failed"

    total_in = sum(s.rows_in for s in job.shards)
    total_out = sum(s.rows_out for s in job.shards)
    aggregated: dict[str, int] = {}
    for s in job.shards:
        for k, v in s.step_counters.items():
            aggregated[k] = aggregated.get(k, 0) + v

    finalized = job.model_copy(
        update={
            "status": new_status,
            "total_rows_in": total_in,
            "total_rows_out": total_out,
            "aggregated_counters": aggregated,
            "updated_at": _now_iso(),
        }
    )
    _save(finalized)
    logger.info(
        "잡 %s 종료: status=%s rows %d→%d",
        job.job_id,
        new_status,
        total_in,
        total_out,
    )
    return finalized
