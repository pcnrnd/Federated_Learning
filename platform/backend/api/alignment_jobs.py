"""사일로 간 수직 정렬 API — HMAC 다이제스트 교집합 (원본 id는 받지 않는다)"""
from __future__ import annotations

from fastapi import APIRouter, Query

from models.alignment_schemas import (
    AlignmentIntersection,
    AlignmentJob,
    AlignmentJobCreate,
    AlignmentReport,
    AlignmentSubmit,
)
from services import alignment_service

router = APIRouter(prefix="/api/alignment-jobs", tags=["alignment-jobs"])


@router.get("", response_model=list[AlignmentJob])
def list_alignments_endpoint() -> list[AlignmentJob]:
    return alignment_service.list_alignments()


@router.post("", response_model=AlignmentJob, status_code=201)
def create_alignment_endpoint(request: AlignmentJobCreate) -> AlignmentJob:
    return alignment_service.create_alignment(request)


@router.get("/{alignment_id}", response_model=AlignmentJob)
def get_alignment_endpoint(alignment_id: str) -> AlignmentJob:
    return alignment_service.get_alignment(alignment_id)


@router.post("/{alignment_id}/submit", response_model=AlignmentJob, status_code=202)
def submit_hashes_endpoint(alignment_id: str, submit: AlignmentSubmit) -> AlignmentJob:
    return alignment_service.submit_hashes(alignment_id, submit)


@router.get("/{alignment_id}/intersection", response_model=AlignmentIntersection)
def get_intersection_endpoint(
    alignment_id: str, silo_id: str = Query(..., description="요청 사일로 (참여자만)")
) -> AlignmentIntersection:
    return alignment_service.get_intersection(alignment_id, silo_id)


@router.post("/{alignment_id}/report", response_model=AlignmentJob)
def report_alignment_endpoint(alignment_id: str, report: AlignmentReport) -> AlignmentJob:
    return alignment_service.report_alignment(alignment_id, report)
