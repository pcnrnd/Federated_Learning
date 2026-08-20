"""통합 대시보드 — 5종 시각화를 단일 요청으로 비동기 병렬 컴포지션.

성능 비교(I/O bound 7~8개 YAML 로드 + 메모리 집계):
  * 순차 호출  : O(n) — 각 시각화가 I/O를 직렬로 수행
  * 본 엔드포인트: O(1) wall-clock — asyncio.gather로 동시 진행
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from services import async_io, visualization_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
async def composite_dashboard_endpoint(
    model_name: str = Query(..., description="대상 모델"),
    version: str = Query(..., description="대상 버전"),
    metric: str = Query(default="accuracy"),
    feature: str | None = Query(default=None, description="histogram 대상 feature (선택)"),
    resource_metric: str = Query(
        default="cpu_pct",
        pattern="^(cpu_pct|mem_pct|gpu_pct|disk_pct)$",
    ),
) -> dict[str, Any]:
    """대시보드용 5종 차트 데이터를 병렬로 수집"""

    async def _ts() -> Any:
        return await async_io.run_sync(
            visualization_service.timeseries,
            model_name=model_name,
            version=version,
            metric=metric,
        )

    async def _bar_resource() -> Any:
        return await async_io.run_sync(
            visualization_service.silo_bar_resource_usage, metric=resource_metric
        )

    async def _heat() -> Any:
        return await async_io.run_sync(
            visualization_service.heatmap_silo_metric,
            model_name=model_name,
            version=version,
        )

    async def _topo() -> Any:
        return await async_io.run_sync(visualization_service.topology)

    async def _hist() -> Any:
        if feature is None:
            return None
        return await async_io.run_sync(
            visualization_service.histogram,
            model_name=model_name,
            version=version,
            feature=feature,
        )

    results = await async_io.gather_calls_safe(
        [_ts(), _bar_resource(), _heat(), _topo(), _hist()]
    )
    keys = ("timeseries", "silo_bar_resource", "heatmap", "topology", "histogram")
    out: dict[str, Any] = {}
    for k, r in zip(keys, results):
        if isinstance(r, Exception):
            out[k] = {"error": str(r)}
        elif r is None:
            out[k] = None
        elif hasattr(r, "model_dump"):
            out[k] = r.model_dump()
        else:
            out[k] = r
    return out
