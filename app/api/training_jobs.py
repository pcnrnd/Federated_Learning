"""학습 잡(Training Job) API — Batch Scheduling 자동화"""
from __future__ import annotations

from fastapi import APIRouter, Query

from models.federated_schemas import TrainingJob, TrainingJobRequest
from services import training_job_service

router = APIRouter(prefix="/api/training-jobs", tags=["training-jobs"])


@router.get("", response_model=list[TrainingJob])
def list_jobs_endpoint(status: str | None = Query(default=None)) -> list[TrainingJob]:
    return training_job_service.list_jobs(status=status)


@router.post("", response_model=TrainingJob, status_code=201)
def create_job_endpoint(request: TrainingJobRequest) -> TrainingJob:
    return training_job_service.create_job(request)


@router.get("/{job_id}", response_model=TrainingJob)
def get_job_endpoint(job_id: str) -> TrainingJob:
    return training_job_service.get_job(job_id)


@router.post("/{job_id}/pause", response_model=TrainingJob)
def pause_job_endpoint(job_id: str) -> TrainingJob:
    return training_job_service.pause_job(job_id)


@router.post("/{job_id}/resume", response_model=TrainingJob)
def resume_job_endpoint(job_id: str) -> TrainingJob:
    return training_job_service.resume_job(job_id)


@router.post("/{job_id}/cancel", response_model=TrainingJob)
def cancel_job_endpoint(job_id: str) -> TrainingJob:
    return training_job_service.cancel_job(job_id)


@router.post("/_tick", response_model=list[str])
def manual_tick_endpoint() -> list[str]:
    """수동 tick 트리거 (테스트/디버깅용 — 평상시 스케줄러가 자동 호출)"""
    return training_job_service.tick()
