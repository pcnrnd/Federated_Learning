"""데이터 정제 (분산/샤딩) 스키마

개인정보 보호:
  * 레시피·잡·결과 어디에도 원시 데이터 필드 없음.
  * 사일로는 행수/카운터만 보고한다.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

JobStatus = Literal["pending", "running", "completed", "partial", "failed"]
ShardStatus = Literal["pending", "running", "completed", "failed"]
StepType = Literal[
    "drop_nulls",
    "clip_outliers",
    "dedupe",
    "cast",
    "normalize",
    "trim_whitespace",
    "lowercase",
    "regex_filter",
]


class CleaningStep(BaseModel):
    """레시피의 단일 정제 단계 — 메타데이터만 (실제 적용은 사일로 SDK)"""

    type: StepType
    params: dict[str, Any] = Field(default_factory=dict)


class CleaningRecipeRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    version: str = Field(..., description="SemVer (예: 1.0.0)")
    description: str = ""
    steps: list[CleaningStep] = Field(..., min_length=1)

    @field_validator("version")
    @classmethod
    def _check_semver(cls, v: str) -> str:
        parts = v.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError("version은 SemVer 형식이어야 합니다 (예: 1.0.0)")
        return v


class CleaningRecipe(BaseModel):
    name: str
    version: str
    description: str
    steps: list[CleaningStep]
    created_at: str


class CleaningJobCreate(BaseModel):
    """잡 생성 요청 — 그룹 멤버 사일로마다 1 샤드를 자동 배정"""

    job_id: str = Field(..., min_length=1, max_length=64)
    recipe_name: str
    recipe_version: str
    group_id: str
    dataset_label: str = Field(
        ...,
        description="사일로가 작업 대상으로 인식하는 데이터셋 식별자 (예: 'patients_2026Q2')",
    )
    notes: str = ""


class ShardAssignment(BaseModel):
    """샤드 → 사일로 배정"""

    shard_index: int = Field(..., ge=0)
    silo_id: str
    status: ShardStatus = "pending"
    rows_in: int = 0
    rows_out: int = 0
    step_counters: dict[str, int] = Field(
        default_factory=dict,
        description="step별 적용 카운트 (예: {'drop_nulls':123,'dedupe':45})",
    )
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class CleaningJob(BaseModel):
    job_id: str
    recipe_name: str
    recipe_version: str
    group_id: str
    dataset_label: str
    status: JobStatus
    shards: list[ShardAssignment]
    total_rows_in: int = 0
    total_rows_out: int = 0
    aggregated_counters: dict[str, int] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    notes: str = ""


class ShardReport(BaseModel):
    """사일로 → 중앙: 샤드 처리 결과 보고 (통계만)"""

    job_id: str
    shard_index: int
    silo_id: str
    rows_in: int = Field(..., ge=0)
    rows_out: int = Field(..., ge=0)
    step_counters: dict[str, int] = Field(default_factory=dict)
    started_at: str
    completed_at: str
    error: str | None = None
