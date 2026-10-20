"""실제 serving route와 입력을 보관하지 않는 비교/요청 메타 계약."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ComparisonGate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    min_pairs: int = Field(ge=1, strict=True)
    window_seconds: int = Field(ge=1, le=86400, strict=True)
    max_age_seconds: int = Field(ge=1, le=86400, strict=True)
    max_error_rate: float = Field(ge=0, le=1)
    max_mean_abs_difference: float = Field(ge=0)
    max_latency_ratio: float | None = Field(default=None, gt=0)


class ServingRouteRequest(BaseModel):
    primary_deployment_id: str = Field(min_length=1)


class ServingPredictRequest(BaseModel):
    inputs: list[Any] = Field(min_length=1)
    request_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class RoleObservation(BaseModel):
    deployment_id: str
    model_name: str
    version: str
    node_id: str | None = None
    image_id: str | None = None
    status: Literal["ok", "error", "interrupted"]
    duration_ms: float | None = None
    error_code: str | None = None
    request_id_echoed: bool = False


class ServingEvent(BaseModel):
    request_id: str
    route_id: str
    generation: int
    owner_epoch: str
    started_at: str
    completed_at: str | None = None
    status: Literal["pending", "completed", "interrupted"] = "pending"
    input_count: int
    primary_deployment_id: str
    shadow_deployment_id: str | None = None
    roles: dict[str, RoleObservation] = Field(default_factory=dict)
    paired: bool = False
    difference_count: int = 0
    mean_abs_difference: float | None = None
    comparison_error: str | None = None


class ServingRoute(BaseModel):
    route_id: str
    primary_deployment_id: str
    shadow_deployment_id: str | None = None
    previous_deployment_id: str | None = None
    shadow_id: str | None = None
    status: Literal["active", "promoted", "rolled_back", "closed"] = "active"
    generation: int = 1
    mirror_pct: float = Field(default=0, ge=0, le=100)
    comparison_gate: ComparisonGate | None = None
    comparison_started_at: str | None = None
    created_at: str
    changed_at: str
    cleanup_deployment_ids: list[str] = Field(default_factory=list)
    cleanup_pending: bool = False
    error: str | None = None


class RoleSummary(BaseModel):
    requests: int = 0
    completed_requests: int = 0
    successes: int = 0
    errors: int = 0
    interrupted: int = 0
    measured_requests: int = 0
    mean_latency_ms: float | None = None
    throughput_rps: float | None = None


class ServingComparison(BaseModel):
    route_id: str
    generation: int
    window_start: str
    window_end: str
    window_seconds: int
    request_count: int
    pending: int
    interrupted: int
    pairs: int
    difference_count: int
    mean_abs_difference: float | None
    latest_pair_at: str | None
    roles: dict[str, RoleSummary]
    paired_roles: dict[str, RoleSummary]
    gate_ready: bool
    gate_reasons: list[str]
    gate: ComparisonGate | None
