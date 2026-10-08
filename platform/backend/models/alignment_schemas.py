"""사일로 간 수직 정렬 작업 스키마 — HMAC 다이제스트·건수만, 원본 id 없음"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

# HMAC-SHA256 hex — 원본 id가 실려 오지 않도록 형식을 강제한다
HashedKey = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
AlignmentStatus = Literal["waiting", "ready"]

MAX_KEYS_PER_SILO = 1_000_000


class AlignmentJobCreate(BaseModel):
    alignment_id: str = Field(..., min_length=1, max_length=64)
    silo_ids: list[str] = Field(..., min_length=2, description="정렬에 참여하는 사일로 (2곳 이상)")
    notes: str = ""

    @field_validator("silo_ids")
    @classmethod
    def _distinct(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("silo_ids에 중복이 있습니다")
        return v


class AlignmentSubmit(BaseModel):
    """사일로 → 중앙: 엔터티 id의 HMAC-SHA256 다이제스트 목록"""

    silo_id: str
    hashed_keys: list[HashedKey] = Field(..., min_length=1, max_length=MAX_KEYS_PER_SILO)


class AlignmentReport(BaseModel):
    """사일로 → 중앙: 정렬 결과 통계 (남은 수·제외 수·순서 지문)"""

    silo_id: str
    submitted: int | None = Field(default=None, ge=0)
    matched: int = Field(..., ge=0)
    excluded: int = Field(..., ge=0)
    order_digest: HashedKey


class AlignmentParticipant(BaseModel):
    silo_id: str
    submitted: int | None = None  # 보낸 다이제스트 수 (None = 아직)
    # 보낸 다이제스트 집합의 지문 — 정렬한 다이제스트를 줄바꿈으로 이은 문자열의 sha256.
    # 사일로가 재실행할 때 이전 제출과 같은 집합인지 확인한다 (건수만으로는 못 가린다).
    submitted_digest: str | None = None
    submitted_at: str | None = None
    matched: int | None = None
    excluded: int | None = None
    order_digest: str | None = None


class AlignmentJob(BaseModel):
    alignment_id: str
    silo_ids: list[str]
    status: AlignmentStatus
    participants: list[AlignmentParticipant]
    intersection_size: int | None = None
    # 모든 참여자가 같은 순서 지문·교집합 크기를 보고하면 True, 어긋나면 False, 대기 중 None
    order_consistent: bool | None = None
    created_at: str
    updated_at: str
    notes: str = ""


class AlignmentIntersection(BaseModel):
    alignment_id: str
    hashed_keys: list[str]
