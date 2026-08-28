"""사일로 리소스 모니터링 스키마

원칙: 모든 사용률은 0~100 백분율. 절대값(코어 수, 바이트)이 필요하면 metadata에 담는다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ResourceLimit(BaseModel):
    """사일로별 자원 임계값 (백분율). None 이면 미감시."""

    silo_id: str
    cpu_pct_max: float | None = Field(default=None, ge=0.0, le=100.0)
    mem_pct_max: float | None = Field(default=None, ge=0.0, le=100.0)
    gpu_pct_max: float | None = Field(default=None, ge=0.0, le=100.0)
    disk_pct_max: float | None = Field(default=None, ge=0.0, le=100.0)


class ResourceSample(BaseModel):
    """사일로 → 중앙 push: 시점 t의 자원 사용률 스냅샷"""

    silo_id: str
    cpu_pct: float = Field(..., ge=0.0, le=100.0)
    mem_pct: float = Field(..., ge=0.0, le=100.0)
    gpu_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    disk_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    timestamp: str


class ResourceAlert(BaseModel):
    alert_id: str
    silo_id: str
    metric: str  # cpu / mem / gpu / disk
    observed: float
    limit: float
    triggered_at: str
    message: str


class ResourceUsageSummary(BaseModel):
    silo_id: str
    last_sample_at: str
    cpu_pct: float
    mem_pct: float
    gpu_pct: float | None
    disk_pct: float | None
    over_budget: bool
