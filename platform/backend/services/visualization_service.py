"""시각화 데이터 컴포지션 서비스.

기존 데이터 소스(metric_store, resource_service, training_round_service,
silo_group_service, deployment_service, drift_detector)를 5종 차트의 입력으로 변환.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from config.federated_manager import load_silo_groups
from config.monitoring_manager import load_baselines
from config.server_manager import load_servers
from models.visualization_schemas import (
    ChartEnvelope,
    HeatmapData,
    HistogramData,
    SiloBarData,
    SiloBarItem,
    TimeSeriesData,
    TimeSeriesPoint,
    TopologyData,
    TopologyEdge,
    TopologyNode,
)
from services import (
    deployment_service,
    metric_store,
    resource_service,
    training_round_service,
)

DEFAULT_METRICS = ("accuracy", "latency_ms", "throughput_rps")


# ---------- 1. timeseries ----------

def timeseries(
    *,
    model_name: str,
    version: str,
    metric: str,
    silo_id: str | None = None,
) -> ChartEnvelope:
    """모델·버전·메트릭에 대한 시간축 추이 (사일로별 시리즈)"""
    samples, _ = metric_store.query(
        model_name=model_name, version=version, metric=metric, node_id=silo_id
    )
    series: dict[str, list[TimeSeriesPoint]] = {}
    for s in samples:
        series.setdefault(s.node_id, []).append(
            TimeSeriesPoint(timestamp=s.timestamp, value=s.value)
        )
    data = TimeSeriesData(series=series)
    return ChartEnvelope(
        chart_type="timeseries",
        title=f"{model_name}@{version} — {metric}",
        x_axis="timestamp",
        y_axis=metric,
        payload=data.model_dump(),
    )


# ---------- 2. histogram ----------

def histogram(
    *, model_name: str, version: str, feature: str
) -> ChartEnvelope:
    """드리프트 베이스라인 분포 (사일로가 사전 push한 히스토그램)"""
    baselines = load_baselines()
    key = f"{model_name}::{version}::{feature}"
    if key not in baselines:
        raise HTTPException(status_code=404, detail=f"베이스라인 없음: {key}")
    b = baselines[key]
    data = HistogramData(bin_edges=b["bin_edges"], bin_counts=b["bin_counts"])
    return ChartEnvelope(
        chart_type="histogram",
        title=f"{model_name}@{version} — {feature} 분포",
        x_axis=feature,
        y_axis="count",
        payload=data.model_dump(),
    )


# ---------- 3. silo_bar ----------

def silo_bar_resource_usage(metric: str = "cpu_pct") -> ChartEnvelope:
    """현재 사일로별 리소스 사용률 (latest sample)"""
    summaries = resource_service.usage_summary()
    items: list[SiloBarItem] = []
    label_map = {"cpu_pct": "CPU %", "mem_pct": "Memory %", "gpu_pct": "GPU %", "disk_pct": "Disk %"}
    for s in summaries:
        value = getattr(s, metric, None)
        if value is None:
            continue
        items.append(SiloBarItem(silo_id=s.silo_id, value=float(value)))
    data = SiloBarData(items=items)
    return ChartEnvelope(
        chart_type="silo_bar",
        title=f"사일로별 {label_map.get(metric, metric)}",
        x_axis="silo_id",
        y_axis=label_map.get(metric, metric),
        payload=data.model_dump(),
    )


def silo_bar_round_contributions(round_id: str) -> ChartEnvelope:
    """특정 학습 라운드의 사일로별 표본수 기여"""
    rnd = training_round_service.get_round(round_id)
    contributions = training_round_service.list_contributions(round_id)
    items = [
        SiloBarItem(silo_id=c.silo_id, value=float(c.sample_count))
        for c in contributions
    ]
    data = SiloBarData(items=items)
    return ChartEnvelope(
        chart_type="silo_bar",
        title=f"라운드 {round_id[:8]} — 사일로별 표본수 기여",
        x_axis="silo_id",
        y_axis="sample_count",
        payload=data.model_dump(),
    )


# ---------- 4. heatmap ----------

def heatmap_silo_metric(
    *,
    model_name: str,
    version: str,
    metrics: tuple[str, ...] = DEFAULT_METRICS,
) -> ChartEnvelope:
    """행=사일로, 열=메트릭, 값=평균값."""
    all_samples, _ = metric_store.query(model_name=model_name, version=version)
    silos = sorted({s.node_id for s in all_samples})
    matrix: list[list[float | None]] = []
    for silo_id in silos:
        row: list[float | None] = []
        for m in metrics:
            silo_samples = [s for s in all_samples if s.node_id == silo_id and s.metric == m]
            if not silo_samples:
                row.append(None)
            else:
                row.append(sum(s.value for s in silo_samples) / len(silo_samples))
        matrix.append(row)
    data = HeatmapData(row_labels=silos, col_labels=list(metrics), matrix=matrix)
    return ChartEnvelope(
        chart_type="heatmap",
        title=f"{model_name}@{version} — 사일로 × 메트릭 평균",
        x_axis="metric",
        y_axis="silo_id",
        payload=data.model_dump(),
    )


# ---------- 5. topology ----------

def topology() -> ChartEnvelope:
    """사일로 그룹 토폴로지: 그룹 → 멤버 사일로, 사일로 → 배포 컨테이너"""
    servers = load_servers()
    groups_raw = load_silo_groups()
    deployments = deployment_service.list_deployments()

    nodes: dict[str, TopologyNode] = {}
    edges: list[TopologyEdge] = []

    # 사일로/노드
    for node_id, info in servers.items():
        over = not resource_service.is_silo_available(node_id)
        nodes[node_id] = TopologyNode(
            id=node_id,
            label=info.get("label", node_id),
            role=info.get("role", "client"),
            over_budget=over,
        )

    # 그룹 → 멤버
    for group_id, group_data in groups_raw.items():
        group_node_id = f"group::{group_id}"
        nodes[group_node_id] = TopologyNode(
            id=group_node_id,
            label=group_id,
            role="group",
            group=group_id,
        )
        for silo_id in group_data.get("member_node_ids", []):
            edges.append(
                TopologyEdge(source=group_node_id, target=silo_id, kind="group")
            )
            if silo_id in nodes:
                nodes[silo_id] = nodes[silo_id].model_copy(update={"group": group_id})

    # 배포 → 노드 (running 만)
    for d in deployments:
        if d.status != "running":
            continue
        deploy_node_id = f"deploy::{d.deployment_id[:8]}"
        nodes[deploy_node_id] = TopologyNode(
            id=deploy_node_id,
            label=f"{d.model_name}@{d.version}",
            role="deployment",
        )
        for silo_id in d.container_map.keys():
            edges.append(
                TopologyEdge(
                    source=deploy_node_id,
                    target=silo_id,
                    kind="deployment",
                    metadata={"strategy": d.strategy, "model": d.model_name},
                )
            )

    data = TopologyData(nodes=list(nodes.values()), edges=edges)
    return ChartEnvelope(
        chart_type="topology",
        title="사일로 그룹/배포 토폴로지",
        payload=data.model_dump(),
    )


# ---------- 메타 ----------

def list_available_charts() -> list[dict[str, Any]]:
    return [
        {"type": "timeseries", "endpoint": "/api/visualizations/timeseries"},
        {"type": "histogram", "endpoint": "/api/visualizations/histogram"},
        {"type": "silo_bar", "endpoint": "/api/visualizations/silo-bar/resource"},
        {"type": "heatmap", "endpoint": "/api/visualizations/heatmap"},
        {"type": "topology", "endpoint": "/api/visualizations/topology"},
    ]
