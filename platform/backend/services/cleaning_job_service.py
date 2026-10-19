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
    AssignedShard,
    CleaningJob,
    CleaningJobCreate,
    CleaningExecutionOptions,
    SchemaConsistency,
    ShardAssignment,
    ShardReport,
)
from services import cleaning_recipe_service, silo_group_service

logger = logging.getLogger(__name__)

_lock = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save(job: CleaningJob) -> None:
    with _lock:
        jobs = load_jobs()
        jobs[job.job_id] = job.model_dump()
        save_jobs(jobs)


def list_jobs(status: str | None = None) -> list[CleaningJob]:
    with _lock:
        raw = load_jobs()
    jobs = [CleaningJob(**v) for v in raw.values()]
    if status:
        jobs = [j for j in jobs if j.status == status]
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    return jobs


def get_job(job_id: str) -> CleaningJob:
    with _lock:
        raw = load_jobs()
    if job_id not in raw:
        raise HTTPException(status_code=404, detail=f"잡 '{job_id}' 없음")
    return CleaningJob(**raw[job_id])


def create_job(request: CleaningJobCreate) -> CleaningJob:
    with _lock:
        return _create_job(request)


def _create_job(request: CleaningJobCreate) -> CleaningJob:
    """그룹 멤버 사일로마다 1개 샤드를 자동 배정"""
    jobs = load_jobs()
    if request.job_id in jobs:
        raise HTTPException(status_code=409, detail=f"잡 '{request.job_id}' 중복")
    if request.job_id in request.depends_on:
        raise HTTPException(status_code=422, detail="정제 작업은 자기 자신에 의존할 수 없습니다")
    for dependency in request.depends_on:
        get_job(dependency)

    # 레시피 + 그룹 사전 검증
    cleaning_recipe_service.get_recipe(request.recipe_name, request.recipe_version)
    group = silo_group_service.get_group(request.group_id)
    if not group.member_node_ids:
        raise HTTPException(
            status_code=400, detail=f"그룹 '{group.group_id}'에 멤버가 없습니다"
        )

    # HFL 루트의 정제 입력은 집계자 자기와 정확한 하위 데이터 보유자를 모두 덮는다.
    # shard 목록을 생성 시 동결하므로 이후 그룹 수정이 실행 중 정제를 바꾸지 않는다.
    members = list(group.member_node_ids)
    if len(set(members)) != len(members):
        raise HTTPException(status_code=409, detail="정제 참여자에 중복된 노드가 있습니다")
    aggregators = set()
    for cluster in silo_group_service.list_groups():
        if cluster.aggregator_node_id in group.member_node_ids:
            if cluster.aggregator_node_id in aggregators or set(members) & set(cluster.member_node_ids):
                raise HTTPException(status_code=409, detail="정제 root/leaf 기원이 겹치거나 집계자 클러스터가 중복됩니다")
            if len(set(cluster.member_node_ids)) != len(cluster.member_node_ids):
                raise HTTPException(status_code=409, detail="정제 하위 참여자가 중복됩니다")
            aggregators.add(cluster.aggregator_node_id)
            members.extend(cluster.member_node_ids)
    shards = [
        ShardAssignment(shard_index=i, silo_id=silo_id, status="pending")
        for i, silo_id in enumerate(members)
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
        **request.model_dump(include=set(CleaningExecutionOptions.model_fields)),
        schedule_id=request.job_id,
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


def start_shard(job_id: str, shard_index: int, silo_id: str,
                claim_id: str | None = None) -> CleaningJob:
    from services.cleaning_execution import start
    return start(job_id, shard_index, silo_id, claim_id)


def report_shard(report: ShardReport) -> CleaningJob:
    from services.cleaning_execution import report as accept_report
    return accept_report(report)

def _finalized(job: CleaningJob) -> CleaningJob:
    """저장 부수효과 없이 terminal shard들에서 완전한 job을 도출한다."""
    if any(s.status in ("pending", "running", "retry_wait") for s in job.shards):
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

    events = list(job.events)
    if new_status in ("failed", "partial"):
        event_id = f"{job.job_id}:{job.generation}:final_failure"
        if not any(e["event_id"] == event_id for e in events):
            events.append({"event_id": event_id, "kind": "failed", "at": _now_iso(),
                           "message": job.blocked_reason or "정제 시도 소진 또는 최종 실패"})
    if (job.status == new_status and job.total_rows_in == total_in
            and job.total_rows_out == total_out and job.aggregated_counters == aggregated
            and job.events == events):
        return job
    return job.model_copy(
        update={
            "status": new_status,
            "total_rows_in": total_in,
            "total_rows_out": total_out,
            "aggregated_counters": aggregated,
            "updated_at": _now_iso(),
            "events": events,
        }
    )


def _maybe_finalize(job: CleaningJob) -> CleaningJob:
    finalized = _finalized(job)
    if finalized is not job:
        _save(finalized)
    return finalized


def schema_consistency(job_id: str) -> SchemaConsistency:
    """샤드들이 보고한 공통 스키마 지문을 비교한다 (값 없이 스키마 일치만)."""
    job = get_job(job_id)
    fingerprints = {s.silo_id: s.schema_fingerprint for s in job.shards}
    groups: dict[str, list[str]] = {}
    for silo_id, fp in fingerprints.items():
        if fp is not None:
            groups.setdefault(fp, []).append(silo_id)
    missing = [silo_id for silo_id, fp in fingerprints.items() if fp is None]
    if len(groups) > 1:
        consistent: bool | None = False
    elif groups and not missing:
        consistent = True
    else:
        consistent = None
    return SchemaConsistency(
        job_id=job_id,
        consistent=consistent,
        fingerprints=fingerprints,
        groups=groups,
        missing=missing,
    )


def list_assigned_shards(silo_id: str, status: str | None = None) -> list[AssignedShard]:
    """사일로에 배정된 샤드 (오래된 잡 먼저). status로 샤드 상태를 거른다."""
    out: list[AssignedShard] = []
    for job in sorted(list_jobs(), key=lambda j: j.created_at):
        from services.cleaning_execution import ready
        if status == "pending" and not ready(job):
            continue
        for shard in job.shards:
            if shard.silo_id != silo_id or (status and shard.status != status):
                continue
            out.append(
                AssignedShard(
                    job_id=job.job_id,
                    shard_index=shard.shard_index,
                    silo_id=silo_id,
                    status=shard.status,
                    recipe_name=job.recipe_name,
                    recipe_version=job.recipe_version,
                    dataset_label=job.dataset_label,
                    job_status=job.status,
                    created_at=job.created_at,
                    generation=job.generation, partitions=job.partitions,
                    parallelism=job.parallelism, timeout_seconds=job.timeout_seconds,
                )
            )
    return out
