"""리소스 모니터링 API"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from models.common_schemas import IngestResponse, OkResponse, PaginatedResponse
from models.resource_schemas import (
    ResourceAlert,
    ResourceLimit,
    ResourceSample,
    ResourceUsageSummary,
)
from services import resource_service

router = APIRouter(prefix="/api/resources", tags=["resources"])


@router.post("/limits", response_model=ResourceLimit, status_code=201)
def set_limit_endpoint(limit: ResourceLimit) -> ResourceLimit:
    return resource_service.set_limit(limit)


@router.get("/limits", response_model=list[ResourceLimit])
def list_limits_endpoint() -> list[ResourceLimit]:
    return resource_service.list_limits()


@router.get("/limits/{silo_id}", response_model=ResourceLimit)
def get_limit_endpoint(silo_id: str) -> ResourceLimit:
    limit = resource_service.get_limit(silo_id)
    if limit is None:
        raise HTTPException(status_code=404, detail=f"임계값 없음: {silo_id}")
    return limit


@router.delete("/limits/{silo_id}", response_model=OkResponse)
def delete_limit_endpoint(silo_id: str) -> OkResponse:
    resource_service.delete_limit(silo_id)
    return OkResponse(ok=True)


@router.post("/samples", status_code=202, response_model=IngestResponse)
def ingest_sample_endpoint(sample: ResourceSample) -> IngestResponse:
    result = resource_service.ingest_sample(sample)
    return IngestResponse(ok=True, alerts=result.get("alerts", []))


@router.get("/samples/{silo_id}", response_model=PaginatedResponse[ResourceSample])
def list_samples_endpoint(
    silo_id: str,
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> PaginatedResponse[ResourceSample]:
    """사일로 리소스 샘플을 시간 범위·페이지네이션으로 조회한다."""
    items, total = resource_service.list_samples(
        silo_id,
        limit=limit,
        start_time=start_time,
        end_time=end_time,
        offset=offset,
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/usage", response_model=list[ResourceUsageSummary])
def usage_summary_endpoint() -> list[ResourceUsageSummary]:
    return resource_service.usage_summary()


@router.get("/alerts", response_model=PaginatedResponse[ResourceAlert])
def list_alerts_endpoint(
    silo_id: str | None = Query(default=None),
    metric: str | None = Query(default=None),
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> PaginatedResponse[ResourceAlert]:
    """리소스 알림을 필터·페이지네이션으로 조회한다."""
    items, total = resource_service.list_alerts(
        silo_id=silo_id,
        metric=metric,
        start_time=start_time,
        end_time=end_time,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)
