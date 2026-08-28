"""사일로 데이터 시각화 스키마 — 공인인증 KPI(시각화 5종 × 사일로 6개) 충족용 데이터 페이로드.

5종 차트:
  * timeseries     — 시간축 메트릭 추이 (라인 차트)
  * histogram      — 분포 (막대)
  * silo_bar       — 사일로 간 비교 (그룹 막대)
  * heatmap        — silo × metric 격자
  * topology       — 사일로 그룹 토폴로지 (노드/엣지)

각 차트는 차트 라이브러리(Chart.js / ECharts / Vega-Lite) 무관하게 매핑 가능한
중립적 JSON 페이로드를 노출한다.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ChartType = Literal["timeseries", "histogram", "silo_bar", "heatmap", "topology"]


class ChartEnvelope(BaseModel):
    chart_type: ChartType
    title: str
    x_axis: str = ""
    y_axis: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------- 1. timeseries ----------

class TimeSeriesPoint(BaseModel):
    timestamp: str
    value: float


class TimeSeriesData(BaseModel):
    series: dict[str, list[TimeSeriesPoint]] = Field(
        default_factory=dict,
        description="silo_id → 시간순 포인트 목록",
    )


# ---------- 2. histogram ----------

class HistogramData(BaseModel):
    bin_edges: list[float]
    bin_counts: list[int]


# ---------- 3. silo_bar ----------

class SiloBarItem(BaseModel):
    silo_id: str
    value: float


class SiloBarData(BaseModel):
    items: list[SiloBarItem]


# ---------- 4. heatmap ----------

class HeatmapData(BaseModel):
    row_labels: list[str]  # silo_id
    col_labels: list[str]  # metric_name
    matrix: list[list[float | None]]


# ---------- 5. topology ----------

class TopologyNode(BaseModel):
    id: str
    label: str
    role: str  # central / client
    group: str | None = None
    over_budget: bool | None = None


class TopologyEdge(BaseModel):
    source: str
    target: str
    kind: Literal["group", "deployment"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class TopologyData(BaseModel):
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
