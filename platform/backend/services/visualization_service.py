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
from models.federated_schemas import TrainingRound
from models.visualization_schemas import (
    ChartEnvelope,
    HeatmapData,
    HistogramData,
    ParticipationCellStatus,
    ParticipationHeatmapData,
    ParticipationRoundMeta,
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
    training_round_service.get_round(round_id)  # 라운드 존재 검증 (없으면 404)
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


_CLOSED_ROUND_STATUSES = ("completed", "failed")


def _round_members(
    r: TrainingRound, groups: dict[str, Any], via: set[str]
) -> set[str]:
    """라운드에 참여해야 했던 사일로 범위.

    스냅샷(없으면 현재 그룹 멤버) ∪ 스냅샷 안 집계자가 맡은 클러스터 멤버 ∪ 실제 대리 제출 출처.
    클러스터 멤버는 라운드의 `cluster_snapshot`을 쓰고, 스냅샷이 없는 이전 라운드만
    **현재 그룹 설정으로 추정**한다.
    """
    snapshot = r.member_snapshot
    if snapshot is None:  # 스냅샷 도입 이전 라운드 → 현재 그룹 멤버로 대체
        snapshot = groups.get(r.group_id, {}).get("member_node_ids", [])
    members = set(snapshot) | via
    if r.cluster_snapshot is not None:
        for cluster_members in r.cluster_snapshot.values():
            members.update(cluster_members)
        return members
    for g in groups.values():
        if g.get("aggregator_node_id") in snapshot:
            members.update(g.get("member_node_ids", []))
    return members


def _participation_cell(
    silo_id: str,
    r: TrainingRound,
    members: set[str],
    samples: dict[str, int],
    via: set[str],
) -> tuple[float | None, ParticipationCellStatus]:
    """판정 순서: contributed → via_aggregator → not_member → missing → pending"""
    if silo_id in samples:
        return float(samples[silo_id]), "contributed"
    if silo_id in via:
        return None, "via_aggregator"
    if silo_id not in members:
        return None, "not_member"
    if r.status in _CLOSED_ROUND_STATUSES:
        return None, "missing"
    return None, "pending"


def heatmap_participation(*, group_id: str | None = None, limit: int = 20) -> ChartEnvelope:
    """행=사일로, 열=최근 limit개 라운드(오래된 → 최근), 값=직접 기여 표본수.

    집계자 경유 사일로는 개별 표본수를 서버가 모르므로 값 없이 via_aggregator로 표시한다.
    클러스터 멤버의 라운드 참여 범위는 라운드 시점 `cluster_snapshot` 기준이며,
    스냅샷이 없는 이전 라운드만 현재 그룹 설정으로 추정한다.
    """
    rounds = training_round_service.list_rounds(group_id=group_id)[:limit][::-1]
    groups = load_silo_groups()

    columns = []
    for r in rounds:
        contributions = training_round_service.list_contributions(r.round_id)
        samples = {c.silo_id: c.sample_count for c in contributions}
        via = {s for c in contributions for s in c.aggregated_from}
        columns.append((r, _round_members(r, groups, via), samples, via))

    rows = sorted(set().union(*(members for _, members, _, _ in columns)))
    matrix: list[list[float | None]] = []
    cell_status: list[list[ParticipationCellStatus]] = []
    for silo_id in rows:
        cells = [_participation_cell(silo_id, *col) for col in columns]
        matrix.append([value for value, _ in cells])
        cell_status.append([status for _, status in cells])

    data = ParticipationHeatmapData(
        row_labels=rows,
        col_labels=[r.round_id[:8] for r in rounds],
        col_meta=[
            ParticipationRoundMeta(
                round_id=r.round_id, status=r.status, created_at=r.created_at, group_id=r.group_id
            )
            for r in rounds
        ],
        matrix=matrix,
        cell_status=cell_status,
    )
    return ChartEnvelope(
        chart_type="heatmap",
        title="사일로 × 라운드 참여",
        x_axis="round",
        y_axis="silo_id",
        payload=data.model_dump(),
    )


# ---------- 5. topology ----------

def topology() -> ChartEnvelope:
    """사일로 그룹 토폴로지: 그룹 → 멤버 사일로, 집계자 → 클러스터 멤버, 배포 → 사일로"""
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

        # 엣지 클러스터: 집계자 → 멤버 (2단 계층)
        aggregator = group_data.get("aggregator_node_id")
        if not aggregator:
            continue
        if aggregator in nodes:
            nodes[aggregator] = nodes[aggregator].model_copy(update={"role": "aggregator"})
        for silo_id in group_data.get("member_node_ids", []):
            if silo_id == aggregator:
                continue
            edges.append(
                TopologyEdge(
                    source=aggregator,
                    target=silo_id,
                    kind="aggregation",
                    metadata={"group_id": group_id},
                )
            )

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
        {"type": "silo_bar", "endpoint": "/api/visualizations/silo-bar/round"},
        {"type": "heatmap", "endpoint": "/api/visualizations/heatmap"},
        {"type": "heatmap", "endpoint": "/api/visualizations/heatmap/participation"},
        {"type": "topology", "endpoint": "/api/visualizations/topology"},
    ]
