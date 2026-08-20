"""공통 API 응답/페이지네이션/에러 스키마"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorResponse(BaseModel):
    """일관된 HTTP 에러 응답 본문"""

    detail: str
    code: str | None = Field(default=None, description="기계 판독용 에러 코드")
    field: str | None = Field(default=None, description="검증 실패 필드 (있을 때)")


class OkResponse(BaseModel):
    """단순 성공 확인"""

    ok: bool = True


class IngestResponse(BaseModel):
    """메트릭/리소스 수집 응답"""

    ok: bool = True
    alerts: list[str] = Field(default_factory=list)


class PaginatedResponse(BaseModel, Generic[T]):
    """페이지네이션 래퍼 — items + total + offset/limit"""

    items: list[T]
    total: int
    offset: int = 0
    limit: int = Field(default=100, ge=1)


class MetricAggregateStats(BaseModel):
    """메트릭 집계 통계"""

    count: float
    mean: float
    min: float
    max: float


class MetricsSummaryResponse(BaseModel):
    """주요 성능 지표 3종 집계 요약"""

    accuracy: MetricAggregateStats
    latency_ms: MetricAggregateStats
    throughput_rps: MetricAggregateStats


class AuditEvent(BaseModel):
    """감사 로그 이벤트 단건"""

    event: str
    timestamp: str | None = None
    extra: dict[str, object] = Field(default_factory=dict)


class DeploymentReconcileResult(BaseModel):
    """배포 기록과 Docker 런타임 상태 정합 결과"""

    deployment_id: str
    previous_status: str
    current_status: str
    reconciled: bool
    changes: list[str] = Field(default_factory=list)
    container_states: dict[str, str] = Field(default_factory=dict)
