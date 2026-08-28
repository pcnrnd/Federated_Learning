"""모델 유지관리: lineage / 섀도우 배포 / A·B 테스트 스키마"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ChangeType = Literal["major", "minor", "patch"]
ShadowStatus = Literal["active", "promoted", "aborted"]
ABStatus = Literal["running", "evaluated", "promoted", "aborted"]
ABWinner = Literal["control", "treatment", "inconclusive"]


class ModelLineageRequest(BaseModel):
    """모델 버전의 부모/유래/변경 메모 등록"""

    parent_version: str | None = Field(
        default=None,
        description="이 버전이 파생된 직전 버전 (SemVer)",
    )
    change_type: ChangeType = "patch"
    change_notes: str = ""
    derived_from_round_id: str | None = Field(
        default=None,
        description="이 버전을 생성한 학습 라운드 ID",
    )


class ModelLineage(BaseModel):
    model_name: str
    version: str
    parent_version: str | None
    change_type: ChangeType
    change_notes: str
    derived_from_round_id: str | None
    recorded_at: str


class LineageNode(BaseModel):
    """lineage-tree 응답용 노드"""

    version: str
    parent_version: str | None
    change_type: ChangeType
    change_notes: str
    children: list["LineageNode"] = Field(default_factory=list)


class ShadowDeploymentRequest(BaseModel):
    """섀도우 배포 시작 요청 — 기존 primary 배포 옆에 신규 버전을 동시 배포"""

    primary_deployment_id: str
    shadow_version: str = Field(..., description="새로 배포할 모델 버전 (이미 레지스트리에 등록되어 있어야 함)")
    target_node_ids: list[str] | None = Field(
        default=None,
        description="미지정 시 primary와 동일한 노드 사용",
    )
    image_tag: str | None = None
    traffic_mirror_pct: float = Field(
        default=10.0,
        ge=0.0,
        le=100.0,
        description="섀도우로 미러링할 트래픽 비율 (메타데이터, 실제 라우팅은 외부 프록시 책임)",
    )


class ShadowDeployment(BaseModel):
    shadow_id: str
    primary_deployment_id: str
    shadow_deployment_id: str
    model_name: str
    primary_version: str
    shadow_version: str
    traffic_mirror_pct: float
    status: ShadowStatus
    created_at: str
    promoted_at: str | None = None
    aborted_at: str | None = None


class ABTestRequest(BaseModel):
    """A·B 테스트 시작 요청"""

    test_id: str = Field(..., min_length=1, max_length=64)
    model_name: str
    control_version: str
    treatment_version: str
    group_id: str
    primary_deployment_id: str
    target_node_ids: list[str] | None = None
    metric: Literal["accuracy", "latency_ms", "throughput_rps"] = "accuracy"
    min_samples_per_arm: int = Field(default=20, ge=2)
    higher_is_better: bool = True
    significance_threshold: float = Field(
        default=2.0,
        ge=0.0,
        description="Welch t-stat의 절대값이 이 이상이면 유의로 본다 (≈p<0.05 대응)",
    )


class ABTest(BaseModel):
    test_id: str
    model_name: str
    control_version: str
    treatment_version: str
    control_deployment_id: str
    treatment_deployment_id: str
    shadow_id: str
    metric: str
    min_samples_per_arm: int
    higher_is_better: bool
    significance_threshold: float
    status: ABStatus
    winner: ABWinner | None = None
    t_stat: float | None = None
    control_mean: float | None = None
    treatment_mean: float | None = None
    control_samples: int = 0
    treatment_samples: int = 0
    created_at: str
    evaluated_at: str | None = None
    promoted_at: str | None = None


class ABTestEvaluation(BaseModel):
    """A·B 테스트 평가 결과"""

    test_id: str
    metric: str
    control_mean: float
    treatment_mean: float
    control_samples: int
    treatment_samples: int
    t_stat: float
    winner: ABWinner
    significant: bool
    message: str


LineageNode.model_rebuild()
