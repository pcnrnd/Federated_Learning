"""영속 정제 occurrence/DAG/attempt 제어. 모든 변경은 동일 저장 잠금을 사용한다."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from models.cleaning_schemas import CleaningJob, ShardAssignment, ShardProgress, ShardReport
from services import cleaning_job_service as jobs


def now() -> datetime:
    return datetime.now(timezone.utc)


def due(value: str | None) -> bool:
    return value is None or datetime.fromisoformat(value.replace("Z", "+00:00")) <= now()


def ready(job: CleaningJob) -> bool:
    if not due(job.scheduled_at) or job.blocked_reason:
        return False
    for dependency in job.depends_on:
        previous = jobs.get_job(dependency)
        if previous.status != "completed" or jobs.schema_consistency(dependency).consistent is not True:
            return False
    return True


def require_training_output(job_id: str) -> CleaningJob:
    job = jobs.get_job(job_id)
    if job.status != "completed" or jobs.schema_consistency(job_id).consistent is not True:
        raise HTTPException(status_code=409, detail="선행 정제 완료·공통 스키마 확인 전 학습 불가")
    if any(not (s.output_id and s.output_hash and s.source_hash and s.recipe_hash) for s in job.shards):
        raise HTTPException(status_code=409, detail="보존된 정제 출력 식별자·해시가 없습니다")
    return job


def owned(job: CleaningJob, index: int, silo_id: str) -> ShardAssignment:
    if not 0 <= index < len(job.shards):
        raise HTTPException(status_code=400, detail="유효하지 않은 shard_index")
    shard = job.shards[index]
    if shard.silo_id != silo_id:
        raise HTTPException(status_code=403, detail="해당 사일로에 배정되지 않은 샤드")
    return shard


def save_shard(job: CleaningJob, index: int, shard: ShardAssignment) -> CleaningJob:
    shards = list(job.shards)
    shards[index] = shard
    running = any(s.status == "running" for s in shards)
    changed = job.model_copy(update={"shards": shards, "updated_at": now().isoformat(),
                                     "status": "running" if running else "pending"})
    jobs._save(changed)
    return jobs._maybe_finalize(changed)


def start(job_id: str, index: int, silo_id: str, claim_id: str | None) -> CleaningJob:
    with jobs._lock:
        job = jobs.get_job(job_id)
        shard = owned(job, index, silo_id)
        if claim_id and shard.status == "running" and shard.claim_id == claim_id:
            if shard.deadline_at and due(shard.deadline_at):
                save_shard(job, index, failed(job, shard, "정제 실행 시간초과", True))
                raise HTTPException(status_code=409, detail="claim 실행권한 시간초과")
            return job  # claim 응답 유실 재전송은 같은 실행권한을 돌려준다.
        if not ready(job) or shard.status not in ("pending", "retry_wait") or not due(shard.next_attempt_at):
            raise HTTPException(status_code=409, detail="정제 실행 시각·의존·샤드 상태가 준비되지 않았습니다")
        token = uuid.uuid4().hex
        stamp = now().isoformat()
        updated = shard.model_copy(update={"status": "running", "attempt": shard.attempt + 1,
            "attempt_id": token, "claim_id": claim_id, "started_at": stamp,
            "deadline_at": (now() + timedelta(seconds=job.timeout_seconds)).isoformat(),
            "completed_at": None, "next_attempt_at": None, "error": None,
            "processed_units": 0, "total_units": 0, "stage": "loading",
            "attempts": [*shard.attempts, {"attempt_id": token, "generation": job.generation,
                         "attempt": shard.attempt + 1, "started_at": stamp, "status": "running"}]})
        return save_shard(job, index, updated)


def check_token(job: CleaningJob, shard: ShardAssignment, token: str | None) -> None:
    # 최초 구 SDK의 무토큰 제출 계약만 보존한다. retry/reschedule은 반드시 실행권한 필요.
    if token != shard.attempt_id and (token is not None or shard.attempt > 1 or job.generation > 0):
        raise HTTPException(status_code=409, detail="만료되거나 다른 정제 attempt 보고")


def failed(job: CleaningJob, shard: ShardAssignment, error: str, retryable: bool) -> ShardAssignment:
    retry = retryable and shard.attempt < job.max_attempts
    history = [dict(a) for a in shard.attempts]
    if history:
        history[-1].update(status="failed", error=error, completed_at=now().isoformat())
    return shard.model_copy(update={"status": "retry_wait" if retry else "failed",
        "error": error, "completed_at": now().isoformat(), "stage": "retry_wait" if retry else "failed",
        "next_attempt_at": (now() + timedelta(seconds=job.retry_backoff_seconds)).isoformat() if retry else None,
        "attempts": history, "rows_in": 0, "rows_out": 0, "step_counters": {},
        "output_id": None, "output_hash": None, "source_hash": None, "recipe_hash": None})


def report(payload: ShardReport) -> CleaningJob:
    if payload.rows_out > payload.rows_in:
        raise HTTPException(status_code=400, detail="rows_out > rows_in 은 불가능합니다")
    digest = hashlib.sha256(json.dumps(payload.model_dump(), sort_keys=True).encode()).hexdigest()
    with jobs._lock:
        job = jobs.get_job(payload.job_id)
        shard = owned(job, payload.shard_index, payload.silo_id)
        check_token(job, shard, payload.attempt_id)
        if payload.attempt_id and shard.report_digest == digest:
            return job
        if shard.status not in ("running", "pending") or not ready(job):
            raise HTTPException(status_code=409, detail="현재 샤드 실행권한으로 보고할 수 없습니다")
        if shard.deadline_at and due(shard.deadline_at):
            save_shard(job, payload.shard_index, failed(job, shard, "정제 실행 시간초과", True))
            raise HTTPException(status_code=409, detail="정제 deadline 이후 보고")
        if payload.error:
            updated = failed(job, shard, payload.error, payload.retryable)
        else:
            values = payload.model_dump(exclude={"job_id", "shard_index", "silo_id", "retryable", "attempt_id"})
            history = [dict(a) for a in shard.attempts]
            if history:
                history[-1].update(status="completed", completed_at=payload.completed_at,
                                   output_id=payload.output_id, output_hash=payload.output_hash)
            updated = shard.model_copy(update={**values, "status": "completed", "stage": "completed",
                "processed_units": shard.total_units, "attempts": history})
        updated.report_digest = digest
        return save_shard(job, payload.shard_index, updated)


def progress(job_id: str, index: int, payload: ShardProgress) -> CleaningJob:
    with jobs._lock:
        job = jobs.get_job(job_id)
        shard = owned(job, index, payload.silo_id)
        check_token(job, shard, payload.attempt_id)
        if shard.status != "running" or due(shard.deadline_at):
            raise HTTPException(status_code=409, detail="진행 보고 실행권한 만료")
        if not shard.processed_units <= payload.processed_units <= payload.total_units:
            raise HTTPException(status_code=422, detail="진행량은 단조 증가하며 전체량 이하여야 합니다")
        return save_shard(job, index, shard.model_copy(update={
            "processed_units": payload.processed_units, "total_units": payload.total_units, "stage": payload.stage}))


def reschedule(job_id: str, scheduled_at: str) -> CleaningJob:
    with jobs._lock:
        job = jobs.get_job(job_id)
        shards = [ShardAssignment(shard_index=s.shard_index, silo_id=s.silo_id, attempts=s.attempts)
                  for s in job.shards]
        changed = job.model_copy(update={"generation": job.generation + 1, "scheduled_at": scheduled_at,
            "status": "pending", "shards": shards, "blocked_reason": None,
            "total_rows_in": 0, "total_rows_out": 0, "aggregated_counters": {}, "updated_at": now().isoformat()})
        jobs._save(changed)
        return changed


def tick() -> list[str]:
    changed_ids: list[str] = []
    with jobs._lock:
        for job in jobs.list_jobs():
            if job.status not in ("pending", "running"):
                continue
            bad = [d for d in job.depends_on if jobs.get_job(d).status in ("failed", "partial")
                   or (jobs.get_job(d).status == "completed" and jobs.schema_consistency(d).consistent is not True)]
            if bad:
                job = job.model_copy(update={"blocked_reason": "선행 정제 실패 또는 스키마 미확인"})
                for shard in job.shards:
                    if shard.status != "completed":
                        job = save_shard(job, shard.shard_index, failed(job, shard, job.blocked_reason, False))
                changed_ids.append(job.job_id)
                continue
            for shard in job.shards:
                if shard.status == "running" and shard.deadline_at is None:
                    start_at = datetime.fromisoformat((shard.started_at or job.updated_at).replace("Z", "+00:00"))
                    deadline = (start_at + timedelta(seconds=job.timeout_seconds)).isoformat()
                    job = save_shard(job, shard.shard_index, shard.model_copy(update={"deadline_at": deadline}))
                    shard = job.shards[shard.shard_index]
                if shard.status == "running" and due(shard.deadline_at):
                    job = save_shard(job, shard.shard_index, failed(job, shard, "정제 실행 시간초과", True))
                    changed_ids.append(job.job_id)
                elif shard.status == "retry_wait" and due(shard.next_attempt_at):
                    job = save_shard(job, shard.shard_index, shard.model_copy(update={"status": "pending"}))
        latest: dict[str, CleaningJob] = {}
        for job in jobs.list_jobs():
            key = job.schedule_id or job.job_id
            if key not in latest or latest[key].occurrence < job.occurrence:
                latest[key] = job
        for root_id, job in latest.items():
            if not job.interval_seconds or job.status not in ("completed", "failed", "partial"):
                continue
            if job.max_occurrences and job.occurrence >= job.max_occurrences:
                continue
            next_due = datetime.fromisoformat((job.scheduled_at or job.created_at).replace("Z", "+00:00")) + timedelta(seconds=job.interval_seconds)
            if next_due > now():
                continue
            identity = hashlib.sha256(root_id.encode()).hexdigest()[:20]
            next_id = f"schedule-{identity}-{job.occurrence + 1}"
            clone = job.model_copy(update={"job_id": next_id, "occurrence": job.occurrence + 1,
                "generation": 0, "scheduled_at": next_due.isoformat(), "status": "pending",
                "shards": [ShardAssignment(shard_index=s.shard_index, silo_id=s.silo_id) for s in job.shards],
                "total_rows_in": 0, "total_rows_out": 0, "aggregated_counters": {}, "events": [],
                "blocked_reason": None, "created_at": now().isoformat(), "updated_at": now().isoformat()})
            jobs._save(clone)
            changed_ids.append(next_id)
    return changed_ids
