"""연합학습 사일로 그룹/학습 라운드/파라미터 수집 스키마"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

RoundStatus = Literal["open", "aggregating", "completed", "failed"]
JobScheduleKind = Literal["manual", "chain", "interval"]
JobStatus = Literal["active", "paused", "completed", "cancelled", "failed"]
# 학습 엔진: native = 사일로 워커가 기여를 push(기존), flower = 백엔드가 SuperLink에 Flower 실행을 제출.
# 필드가 없는 기존 기록은 native다(저장 기록은 필드 추가만 — 이전 이미지가 새 기록을 읽을 수 있음).
TrainingEngine = Literal["native", "flower"]


class SiloGroupRequest(BaseModel):
    """사일로 그룹 생성/수정 요청"""

    group_id: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    member_node_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    aggregator_node_id: str | None = Field(
        default=None,
        description="값이 있으면 엣지 클러스터 — 해당 노드가 멤버들의 로컬 집계자",
    )


class SiloGroup(BaseModel):
    """사일로 그룹"""

    group_id: str
    description: str
    member_node_ids: list[str]
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    # None = 일반(루트) 그룹, 값 있음 = 엣지 클러스터 (해당 노드가 로컬 집계자)
    aggregator_node_id: str | None = None


class SiloMemberInfo(BaseModel):
    """그룹 멤버 노드 + servers.yaml 조인 정보"""

    node_id: str
    label: str
    base_url: str | None = None
    role: str | None = None
    in_servers_yaml: bool = False


class LiveLearning(BaseModel):
    """새 live ridge 모델 공간. 기존 learning=None 호출은 closed-form 호환이다."""
    solver: Literal["ridge_gradient_v1"] = "ridge_gradient_v1"
    features: list[str] = Field(default_factory=lambda: ["x1", "x2", "x3"])
    target: str = "y"
    l2: float = Field(default=0.001, ge=0, allow_inf_nan=False, strict=True)
    step_size: float = Field(default=0.0001, gt=0, allow_inf_nan=False, strict=True)
    steps: int = Field(default=1, ge=1, le=1000, strict=True)
    initial_parameters: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])

    @model_validator(mode="before")
    @classmethod
    def finite_initial(cls, value):
        from silo_sdk.training_protocol import vector
        if isinstance(value, dict) and "initial_parameters" in value:
            vector(value["initial_parameters"])
        return value

    @model_validator(mode="after")
    def space(self):
        from silo_sdk.training_protocol import vector
        if (not self.features or any(not f for f in self.features)
                or len(set(self.features)) != len(self.features) or not self.target
                or self.target in self.features):
            raise ValueError("특징/타깃 이름은 비어 있거나 겹칠 수 없습니다")
        self.initial_parameters = vector(self.initial_parameters, len(self.features) + 1)
        return self


class TrainingRoundCreate(BaseModel):
    """학습 라운드 생성 요청"""

    model_name: str
    version: str
    group_id: str
    min_contributions: int = Field(default=2, ge=1, description="집계 시작 최소 기여수")
    notes: str = ""
    cleaning_job_id: str | None = Field(
        default=None, description="학습 입력을 만든 성공 정제 작업 — 보존 출력 스냅샷 사용"
    )
    learning: LiveLearning | None = None
    parent_round_id: str | None = None
    worker_endpoints: dict[str, str] = Field(default_factory=dict)


class ParameterContribution(BaseModel):
    """사일로의 라운드 기여 (파라미터 평탄화 벡터 + 가중치용 샘플수)"""

    round_id: str
    silo_id: str
    sample_count: int = Field(..., ge=1, description="가중평균(FedAvg)용 로컬 학습 표본수")
    parameters: list[float] = Field(..., min_length=1, description="평탄화된 파라미터 벡터")
    checksum: str | None = None
    # 집계자가 대리 제출 시: 로컬 평균에 포함된 하위 노드 id 목록 (평면 제출이면 생략)
    aggregated_from: list[str] = Field(default_factory=list)
    # 정제 → 학습: 레시피로 정제한 로컬 데이터로 학습했을 때의 통계 (행 수·학습 오차만)
    rows_before_cleaning: int | None = Field(default=None, ge=0)
    rows_after_cleaning: int | None = Field(default=None, ge=0)
    train_rmse: float | None = Field(default=None, ge=0, description="로컬 학습 RMSE")
    base_checksum: str | None = None
    space_checksum: str | None = None
    envelope_checksum: str | None = None
    origins: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def _rows_shrink(self) -> ParameterContribution:
        before, after = self.rows_before_cleaning, self.rows_after_cleaning
        if before is not None and after is not None and after > before:
            raise ValueError("rows_after_cleaning이 rows_before_cleaning보다 클 수 없습니다")
        return self

    def cleaning_stats(self) -> dict[str, float | int]:
        """값이 있는 정제 통계만 (없으면 빈 dict)"""
        stats = {
            "rows_before_cleaning": self.rows_before_cleaning,
            "rows_after_cleaning": self.rows_after_cleaning,
            "train_rmse": self.train_rmse,
        }
        return {k: v for k, v in stats.items() if v is not None}


class ParameterContributionRecord(BaseModel):
    """저장된 기여 기록 (조회용)"""

    round_id: str
    silo_id: str
    sample_count: int
    parameter_dim: int
    submitted_at: str
    checksum: str | None = None
    # 대리 제출 출처(provenance) — 리니지·감사용. id 목록일 뿐 원시 데이터가 아니다.
    aggregated_from: list[str] = Field(default_factory=list)
    rows_before_cleaning: int | None = None
    rows_after_cleaning: int | None = None
    train_rmse: float | None = None
    base_checksum: str | None = None
    space_checksum: str | None = None
    envelope_checksum: str | None = None
    origins: list[dict[str, Any]] | None = None


class TrainingExecutionFailure(BaseModel):
    silo_id: str
    error_code: Literal["input_missing", "invalid_model_or_input"]


class TrainingRound(BaseModel):
    round_id: str
    model_name: str
    version: str
    group_id: str
    min_contributions: int
    status: RoundStatus
    contributors: list[str] = Field(default_factory=list, description="기여 완료 silo_id 목록")
    total_samples: int = 0
    aggregated_parameter_dim: int | None = None
    aggregated_at: str | None = None
    created_at: str
    notes: str = ""
    error: str | None = None
    # open 시점 그룹 멤버 스냅샷 — 라운드 중 그룹 변경 무효화 (pending 규칙).
    # None = 스냅샷 도입 이전 레코드 → 현재 그룹 멤버십으로 폴백.
    # []   = 멤버 0명인 그룹의 진짜 빈 스냅샷 → 기여 전부 403 (폴백하지 않는다).
    member_snapshot: list[str] | None = None
    # open 시점 클러스터 스냅샷 — 집계자 → 클러스터 멤버 (member_snapshot 안 집계자만).
    # None = 도입 이전 레코드 → 현재 그룹 설정으로 추정. {} = 집계자 없음 (추정하지 않는다).
    cluster_snapshot: dict[str, list[str]] | None = None
    # 사일로별 정제 통계 — 정제 전후 행 수·학습 오차 (레시피로 정제해 학습한 기여만)
    cleaning_stats: dict[str, dict[str, float | int]] = Field(default_factory=dict)
    cleaning_job_id: str | None = None  # 학습 입력을 만든 정제 작업 (None = 연결 없음)
    cleaning_snapshot: dict[str, dict[str, str | int | None]] | None = None
    learning: LiveLearning | None = None
    parent_round_id: str | None = None
    base_parameters: list[float] | None = None
    base_checksum: str | None = None
    space_checksum: str | None = None
    transport_snapshot: dict[str, str] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    execution_errors: dict[str, dict[str, str]] = Field(default_factory=dict)
    job_id: str | None = None
    job_occurrence: int | None = None
    opening_request_hash: str | None = None
    engine: TrainingEngine = "native"
    flower_run_id: int | None = None  # engine=flower: 이 라운드로 제출한 Flower run ID
    flower_submitted_at: str | None = None


class AggregateResult(BaseModel):
    """FedAvg 집계 결과 (외부 다운로드용)"""

    round_id: str
    parameter_dim: int
    parameters: list[float]
    total_samples: int
    contributor_count: int
    aggregated_at: str
    result_id: str | None = None
    checksum: str | None = None
    format: str = "parameters-v1"
    model_name: str | None = None
    version: str | None = None
    features: list[str] | None = None
    target: str | None = None
    learning: dict[str, Any] | None = None
    base_checksum: str | None = None
    space_checksum: str | None = None
    origins: list[dict[str, Any]] | None = None


class TrainingJobRequest(BaseModel):
    """학습 잡 생성 요청

    스케줄:
      * manual   — 사용자가 다음 라운드를 직접 트리거 (자동 진행 X)
      * chain    — 이전 라운드 완료 직후 다음 라운드 자동 open
      * interval — 이전 라운드 완료 후 N초 경과 시 다음 라운드 open
    """

    job_id: str = Field(..., min_length=1, max_length=64)
    model_name: str
    version: str
    group_id: str
    schedule_kind: JobScheduleKind = "chain"
    interval_seconds: int = Field(default=0, ge=0)
    min_contributions: int = Field(default=2, ge=1)
    max_rounds: int = Field(default=10, ge=1, le=10_000)
    notes: str = ""
    retraining_event_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$",
        description="재교육 소유 이벤트. 일반 잡은 None이며 원장 장애와 독립이다")
    cleaning_job_id: str | None = Field(
        default=None, description="정제 작업 — 이 잡이 여는 라운드에 그대로 기록된다"
    )
    learning: LiveLearning | None = None
    worker_endpoints: dict[str, str] = Field(default_factory=dict)
    engine: TrainingEngine = Field(
        default="native", description="flower면 라운드마다 백엔드가 Flower 실행 1회를 제출(live learning 필요)"
    )


class RoundOpeningIntent(BaseModel):
    """라운드 저장과 YAML 잡 연결 사이를 복구하는 고정 생성 요청."""
    round_id: str
    occurrence: int = Field(ge=1)
    request: TrainingRoundCreate


class TrainingJob(BaseModel):
    job_id: str
    model_name: str
    version: str
    group_id: str
    schedule_kind: JobScheduleKind
    interval_seconds: int
    min_contributions: int
    max_rounds: int
    status: JobStatus
    rounds_completed: int = 0
    rounds_failed: int = 0
    current_round_id: str | None = None
    last_round_completed_at: str | None = None
    created_at: str
    updated_at: str
    notes: str = ""
    retraining_event_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error: str | None = None
    cleaning_job_id: str | None = None
    learning: LiveLearning | None = None
    worker_endpoints: dict[str, str] = Field(default_factory=dict)
    last_completed_round_id: str | None = None
    opening_intent: RoundOpeningIntent | None = None
    engine: TrainingEngine = "native"
