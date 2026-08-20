"""대시보드 통합 엔드포인트 — 5종 차트 병렬 컴포지션 테스트"""
from __future__ import annotations

import pytest

from models.monitoring_schemas import BaselineRequest, MetricIngest
from models.packaging_schemas import ModelRegisterRequest
from models.resource_schemas import ResourceSample
from services import drift_detector, metric_store, model_registry, resource_service
from services.visualization_service import (
    silo_bar_resource_usage,
    timeseries,
)


@pytest.fixture(autouse=True)
def _seed(tmp_path):
    weights = tmp_path / "m.pt"
    weights.write_bytes(b"")
    model_registry.register_model(
        ModelRegisterRequest(
            name="alpha",
            version="1.0.0",
            framework="pytorch",
            weights_path=str(weights),
        )
    )
    for i in range(1, 4):
        metric_store.ingest(
            MetricIngest(
                node_id=f"silo-{i}",
                model_name="alpha",
                version="1.0.0",
                metric="accuracy",
                value=0.5 + 0.1 * i,
                timestamp=f"2026-05-14T00:00:0{i}Z",
            )
        )
        resource_service.ingest_sample(
            ResourceSample(
                silo_id=f"silo-{i}",
                cpu_pct=10.0 * i,
                mem_pct=20.0,
                timestamp="2026-05-14T00:00:00Z",
            )
        )
    drift_detector.set_baseline(
        BaselineRequest(
            model_name="alpha",
            version="1.0.0",
            feature="age",
            bin_edges=[0.0, 10.0, 20.0, 30.0],
            bin_counts=[10, 20, 30],
        )
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_composite_dashboard_returns_5_charts():
    from api.dashboard import composite_dashboard_endpoint

    result = await composite_dashboard_endpoint(
        model_name="alpha",
        version="1.0.0",
        metric="accuracy",
        feature="age",
        resource_metric="cpu_pct",
    )

    assert set(result.keys()) == {
        "timeseries",
        "silo_bar_resource",
        "heatmap",
        "topology",
        "histogram",
    }
    assert result["histogram"]["chart_type"] == "histogram"
    assert result["timeseries"]["chart_type"] == "timeseries"
    # 5개 모두 정상 (Exception 객체 아님)
    assert not any(isinstance(v, Exception) for v in result.values())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_composite_dashboard_skips_histogram_when_feature_missing():
    from api.dashboard import composite_dashboard_endpoint

    result = await composite_dashboard_endpoint(
        model_name="alpha", version="1.0.0", metric="accuracy", feature=None
    )

    assert result["histogram"] is None
    assert result["timeseries"]["chart_type"] == "timeseries"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_composite_dashboard_partial_failure_isolated():
    """histogram이 미등록 feature를 요청해도 다른 차트는 영향 없음"""
    from api.dashboard import composite_dashboard_endpoint

    result = await composite_dashboard_endpoint(
        model_name="alpha",
        version="1.0.0",
        metric="accuracy",
        feature="ghost_feature",
        resource_metric="cpu_pct",
    )

    # histogram 실패는 error 필드로 격리
    assert isinstance(result["histogram"], dict) and "error" in result["histogram"]
    # 다른 차트는 정상
    assert result["timeseries"]["chart_type"] == "timeseries"
    assert result["topology"]["chart_type"] == "topology"


@pytest.mark.unit
def test_visualization_helpers_remain_sync():
    """기존 동기 시각화 helper는 그대로 동작 (호환성 보장)"""
    env = timeseries(model_name="alpha", version="1.0.0", metric="accuracy")
    assert env.chart_type == "timeseries"

    env2 = silo_bar_resource_usage(metric="cpu_pct")
    assert env2.chart_type == "silo_bar"
    assert len(env2.payload["items"]) == 3
