"""데이터 정제 (분산/샤딩) 스키마

개인정보 보호:
  * 레시피·잡·결과 어디에도 원시 데이터 필드 없음.
  * 사일로는 행수/카운터만 보고한다.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

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
    "map_schema",
    "validate_schema",
    "union_sources",
    "join_sources",
]
# 공통 스키마 지문 = sha256 hex — 원본 값이 실려 오지 않도록 형식을 강제한다
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ColumnType = Literal["str", "int", "float", "bool"]


class CleaningStep(BaseModel):
    """레시피의 단일 정제 단계 — 메타데이터만 (실제 적용은 사일로 SDK)"""

    type: StepType
    params: dict[str, Any] = Field(default_factory=dict)


class ColumnSpec(BaseModel):
    """공통 스키마 컬럼 — 형식과 선택적 허용 범위 (validate_schema 기준)"""

    type: ColumnType
    min: float | None = None
    max: float | None = None


class UnitSpec(BaseModel):
    """단위 변환 — 기준 단위 값 = 원천 값 × scale + offset"""

    scale: float = 1.0
    offset: float = 0.0


class SourceMapping(BaseModel):
    """원천 하나의 매핑 — 원천 컬럼 → 공통 컬럼, 단위·코드표 지정"""

    format: Literal["table", "records"] = "table"
    columns: dict[str, str] = Field(..., min_length=1, description="원천 컬럼 → 공통 컬럼")
    units: dict[str, str] = Field(default_factory=dict, description="공통 컬럼 → 단위 이름")
    codes: dict[str, str] = Field(default_factory=dict, description="공통 컬럼 → 코드표 이름")
    # records 형식(JSON 기록) 전용 — 한 기록 = 엔터티·속성 코드·값·단위·관측 시각
    attribute_field: str | None = None
    attribute_codes: str | None = Field(default=None, description="속성 코드 → 공통 컬럼 코드표")
    value_field: str | None = None
    unit_field: str | None = None
    time_field: str | None = None


class CleaningMapping(BaseModel):
    """레시피 매핑표 — 컬럼 대응·형 변환·단위 배율/오프셋·코드표 (메타데이터만, 원시 값 없음)"""

    key: str = "id"
    common_schema: dict[str, ColumnSpec] = Field(..., min_length=1)
    sources: dict[str, SourceMapping] = Field(default_factory=dict)
    units: dict[str, dict[str, UnitSpec]] = Field(default_factory=dict)
    codes: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_references(self) -> CleaningMapping:
        schema = self.common_schema
        if self.key not in schema:
            raise ValueError(f"key '{self.key}'가 공통 스키마에 없습니다")
        for col in self.units:
            if col not in schema:
                raise ValueError(f"단위표 컬럼 '{col}'가 공통 스키마에 없습니다")
        for name, src in self.sources.items():
            for col in src.columns.values():
                if col not in schema:
                    raise ValueError(f"원천 '{name}': 대응 컬럼 '{col}'가 공통 스키마에 없습니다")
            for col, unit in src.units.items():
                if unit not in self.units.get(col, {}):
                    raise ValueError(f"원천 '{name}': 단위표에 '{col}' 단위 '{unit}'가 없습니다")
            tables = [*src.codes.values(), *([src.attribute_codes] if src.attribute_codes else [])]
            for table in tables:
                if table not in self.codes:
                    raise ValueError(f"원천 '{name}': 코드표 '{table}'가 없습니다")
            if src.format == "records" and not (src.attribute_field and src.value_field):
                raise ValueError(f"원천 '{name}': 기록 형식은 attribute_field·value_field가 필요합니다")
        return self


class CleaningRecipeRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    version: str = Field(..., description="SemVer (예: 1.0.0)")
    description: str = ""
    steps: list[CleaningStep] = Field(..., min_length=1)
    mapping: CleaningMapping | None = Field(
        default=None, description="다원천 단계(map_schema 등)용 매핑표"
    )

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
    mapping: CleaningMapping | None = None


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
    schema_fingerprint: Fingerprint | None = None


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
    schema_fingerprint: Fingerprint | None = Field(
        default=None, description="정제 결과 공통 스키마 지문 (정렬된 컬럼:형식의 sha256)"
    )


class SchemaConsistency(BaseModel):
    """사일로 간 공통 스키마 지문 비교 결과

    consistent: 모든 샤드 지문이 같으면 True, 서로 다른 지문이 있으면 False,
    아직 지문을 보고하지 않은 샤드가 있고 불일치도 없으면 None(판정 대기).
    """

    job_id: str
    consistent: bool | None
    fingerprints: dict[str, str | None]
    groups: dict[str, list[str]]
    missing: list[str]
