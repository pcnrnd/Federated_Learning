"""시각화 API — 5종 차트의 데이터 페이로드"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from models.visualization_schemas import ChartEnvelope
from services import visualization_service

router = APIRouter(prefix="/api/visualizations", tags=["visualizations"])


@router.get("")
def list_charts_endpoint() -> list[dict[str, Any]]:
    """사용 가능한 5종 차트 목록"""
    return visualization_service.list_available_charts()


@router.get("/timeseries", response_model=ChartEnvelope)
def timeseries_endpoint(
    model_name: str,
    version: str,
    metric: str = Query(default="accuracy"),
    silo_id: str | None = Query(default=None),
) -> ChartEnvelope:
    return visualization_service.timeseries(
        model_name=model_name, version=version, metric=metric, silo_id=silo_id
    )


@router.get("/histogram", response_model=ChartEnvelope)
def histogram_endpoint(model_name: str, version: str, feature: str) -> ChartEnvelope:
    return visualization_service.histogram(
        model_name=model_name, version=version, feature=feature
    )


@router.get("/silo-bar/resource", response_model=ChartEnvelope)
def silo_bar_resource_endpoint(
    metric: str = Query(default="cpu_pct", pattern="^(cpu_pct|mem_pct|gpu_pct|disk_pct)$"),
) -> ChartEnvelope:
    return visualization_service.silo_bar_resource_usage(metric=metric)


@router.get("/silo-bar/round", response_model=ChartEnvelope)
def silo_bar_round_endpoint(round_id: str) -> ChartEnvelope:
    return visualization_service.silo_bar_round_contributions(round_id)


@router.get("/heatmap", response_model=ChartEnvelope)
def heatmap_endpoint(model_name: str, version: str) -> ChartEnvelope:
    return visualization_service.heatmap_silo_metric(
        model_name=model_name, version=version
    )


@router.get("/topology", response_model=ChartEnvelope)
def topology_endpoint() -> ChartEnvelope:
    return visualization_service.topology()
