"""연합학습 사일로 그룹/학습 라운드/파라미터 수집 스키마"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RoundStatus = Literal["open", "aggregating", "completed", "failed"]
JobScheduleKind = Literal["manual", "chain", "interval"]
JobStatus = Literal["active", "paused", "completed", "cancelled", "failed"]


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


class TrainingRoundCreate(BaseModel):
    """학습 라운드 생성 요청"""

    model_name: str
    version: str
    group_id: str
    min_contributions: int = Field(default=2, ge=1, description="집계 시작 최소 기여수")
    notes: str = ""


class ParameterContribution(BaseModel):
    """사일로의 라운드 기여 (파라미터 평탄화 벡터 + 가중치용 샘플수)"""

    round_id: str
    silo_id: str
    sample_count: int = Field(..., ge=1, description="가중평균(FedAvg)용 로컬 학습 표본수")
    parameters: list[float] = Field(..., min_length=1, description="평탄화된 파라미터 벡터")
    checksum: str | None = None
    # 집계자가 대리 제출 시: 로컬 평균에 포함된 하위 노드 id 목록 (평면 제출이면 생략)
    aggregated_from: list[str] = Field(default_factory=list)


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


class AggregateResult(BaseModel):
    """FedAvg 집계 결과 (외부 다운로드용)"""

    round_id: str
    parameter_dim: int
    parameters: list[float]
    total_samples: int
    contributor_count: int
    aggregated_at: str


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
    error: str | None = None
