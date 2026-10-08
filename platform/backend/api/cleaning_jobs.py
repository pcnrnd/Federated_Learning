"""정제 잡 API"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from models.cleaning_schemas import (
    AssignedShard,
    CleaningJob,
    CleaningJobCreate,
    SchemaConsistency,
    ShardReport,
)
from services import cleaning_job_service

router = APIRouter(prefix="/api/cleaning-jobs", tags=["cleaning-jobs"])
shards_router = APIRouter(prefix="/api/cleaning-shards", tags=["cleaning-jobs"])


@shards_router.get("", response_model=list[AssignedShard])
def list_assigned_shards_endpoint(
    silo_id: str = Query(..., description="배정받은 사일로"),
    status: str | None = Query(default=None, description="샤드 상태 (예: pending)"),
) -> list[AssignedShard]:
    """사일로에 배정된 샤드 — 작업 번호를 몰라도 자기 대기 샤드를 찾는다"""
    return cleaning_job_service.list_assigned_shards(silo_id, status=status)


class ShardStartRequest(BaseModel):
    silo_id: str


@router.get("", response_model=list[CleaningJob])
def list_jobs_endpoint(status: str | None = Query(default=None)) -> list[CleaningJob]:
    return cleaning_job_service.list_jobs(status=status)


@router.post("", response_model=CleaningJob, status_code=201)
def create_job_endpoint(request: CleaningJobCreate) -> CleaningJob:
    return cleaning_job_service.create_job(request)


@router.get("/{job_id}", response_model=CleaningJob)
def get_job_endpoint(job_id: str) -> CleaningJob:
    return cleaning_job_service.get_job(job_id)


@router.get("/{job_id}/schema-consistency", response_model=SchemaConsistency)
def schema_consistency_endpoint(job_id: str) -> SchemaConsistency:
    """사일로 간 공통 스키마 지문 일치 판정"""
    return cleaning_job_service.schema_consistency(job_id)


@router.post("/{job_id}/shards/{shard_index}/start", response_model=CleaningJob)
def start_shard_endpoint(
    job_id: str, shard_index: int, request: ShardStartRequest
) -> CleaningJob:
    return cleaning_job_service.start_shard(job_id, shard_index, request.silo_id)


@router.post("/{job_id}/shards/{shard_index}/report", response_model=CleaningJob)
def report_shard_endpoint(
    job_id: str, shard_index: int, report: ShardReport
) -> CleaningJob:
    # URL 파라미터와 body 일관성 보정
    if report.job_id != job_id or report.shard_index != shard_index:
        report = report.model_copy(update={"job_id": job_id, "shard_index": shard_index})
    return cleaning_job_service.report_shard(report)
