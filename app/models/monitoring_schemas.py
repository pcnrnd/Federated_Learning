"""모니터링/드리프트/알림 Pydantic 스키마

개인정보 보호 원칙:
  * 사일로는 원시 데이터를 절대 전송하지 않는다.
  * 메트릭은 집계값(스칼라)만, 분포는 히스토그램 빈 수치만 전송한다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

MetricName = Literal["accuracy", "latency_ms", "throughput_rps"]
DriftSeverity = Literal["stable", "warning", "critical"]
AlertStatus = Literal["open", "acked", "resolved"]


class MetricIngest(BaseModel):
    """사일로에서 보고하는 성능 메트릭 단일 샘플"""

    node_id: str
    model_name: str
    version: str
    metric: MetricName
    value: float
    timestamp: str = Field(..., description="ISO-8601")


class MetricSample(BaseModel):
    node_id: str
    model_name: str
    version: str
    metric: MetricName
    value: float
    timestamp: str


class DistributionStats(BaseModel):
    """분포 통계 (원시 데이터 미포함). 히스토그램 빈 수치만 전송."""

    node_id: str
    model_name: str
    version: str
    feature: str
    bin_edges: list[float] = Field(..., min_length=2)
    bin_counts: list[int] = Field(..., min_length=1)
    timestamp: str

    @model_validator(mode="after")
    def _check_bins(self) -> DistributionStats:
        if len(self.bin_counts) != len(self.bin_edges) - 1:
            raise ValueError("bin_counts 길이는 bin_edges 길이 - 1 이어야 합니다")
        if any(c < 0 for c in self.bin_counts):
            raise ValueError("bin_counts는 음수가 될 수 없습니다")
        return self


class BaselineRequest(BaseModel):
    """드리프트 비교용 베이스라인 설정"""

    model_name: str
    version: str
    feature: str
    bin_edges: list[float]
    bin_counts: list[int]


class DriftReport(BaseModel):
    model_name: str
    version: str
    feature: str
    psi: float
    severity: DriftSeverity
    baseline_total: int
    current_total: int


class AlertRule(BaseModel):
    """임계값 기반 알림 규칙

    metric=drift 이면 PSI 임계값을 의미한다.
    """

    rule_id: str
    model_name: str
    metric: Literal[MetricName, "drift"]  # type: ignore[valid-type]
    threshold: float
    comparison: Literal["lt", "gt"] = "lt"
    auto_rollback: bool = False


class Alert(BaseModel):
    alert_id: str
    rule_id: str
    model_name: str
    version: str
    metric: str
    observed_value: float
    threshold: float
    status: AlertStatus
    triggered_at: str
    message: str
    triggered_rollback_deployment_id: str | None = None


class RetrainTrigger(BaseModel):
    """자동 재교육 트리거 (외부 워크플로우가 소비)"""

    model_name: str
    version: str
    reason: str
    triggered_at: str
