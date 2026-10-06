"""시각화 5종 차트 데이터 단위 테스트"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from config.federated_manager import load_training_rounds, save_training_rounds
from config.server_manager import save_servers
from models.federated_schemas import (
    ParameterContribution,
    SiloGroupRequest,
    TrainingRoundCreate,
)
from models.monitoring_schemas import BaselineRequest, MetricIngest
from models.packaging_schemas import DeploymentRequest, ModelRegisterRequest
from models.resource_schemas import ResourceLimit, ResourceSample
from services import (
    deployment_service,
    drift_detector,
    metric_store,
    model_registry,
    resource_service,
    silo_group_service,
    training_round_service,
    visualization_service,
)


@pytest.fixture()
def six_silos():
    save_servers(
        {
            f"silo-{i}": {
                "base_url": f"tcp://localhost:23{70 + i}",
                "label": f"silo-{i}",
                "type": "remote",
                "role": "client",
                "tls": False,
            }
            for i in range(1, 7)
        }
    )


@pytest.fixture()
def alpha_model(tmp_path):
    weights = tmp_path / "m.pt"
    weights.write_bytes(b"")
    model_registry.register_model(
        ModelRegisterRequest(
            name="alpha", version="1.0.0", framework="pytorch", weights_path=str(weights)
        )
    )


def _push(silo_id: str, metric: str, value: float, ts: str = "2026-05-14T00:00:00Z") -> None:
    metric_store.ingest(
        MetricIngest(
            node_id=silo_id,
            model_name="alpha",
            version="1.0.0",
            metric=metric,
            value=value,
            timestamp=ts,
        )
    )


@pytest.mark.unit
def test_chart_catalog_has_5_types(six_silos):
    charts = visualization_service.list_available_charts()
    types = {c["type"] for c in charts}
    assert types == {"timeseries", "histogram", "silo_bar", "heatmap", "topology"}
    # 참여 매트릭스·라운드 막대는 기존 유형(heatmap·silo_bar)의 추가 엔드포인트
    endpoints = {c["endpoint"] for c in charts}
    assert "/api/visualizations/heatmap/participation" in endpoints
    assert "/api/visualizations/silo-bar/round" in endpoints


@pytest.mark.unit
def test_timeseries_groups_by_silo(six_silos, alpha_model):
    _push("silo-1", "accuracy", 0.90, "2026-05-14T00:00:00Z")
    _push("silo-1", "accuracy", 0.95, "2026-05-14T00:01:00Z")
    _push("silo-2", "accuracy", 0.80, "2026-05-14T00:00:30Z")

    env = visualization_service.timeseries(
        model_name="alpha", version="1.0.0", metric="accuracy"
    )

    assert env.chart_type == "timeseries"
    series = env.payload["series"]
    assert set(series.keys()) == {"silo-1", "silo-2"}
    assert len(series["silo-1"]) == 2
    # 시간순 정렬 보장
    assert series["silo-1"][0]["value"] == 0.90
    assert series["silo-1"][1]["value"] == 0.95


@pytest.mark.unit
def test_histogram_pulls_from_baseline(six_silos, alpha_model):
    drift_detector.set_baseline(
        BaselineRequest(
            model_name="alpha",
            version="1.0.0",
            feature="age",
            bin_edges=[0.0, 30.0, 60.0, 100.0],
            bin_counts=[10, 20, 5],
        )
    )

    env = visualization_service.histogram(
        model_name="alpha", version="1.0.0", feature="age"
    )

    assert env.chart_type == "histogram"
    assert env.payload["bin_edges"] == [0.0, 30.0, 60.0, 100.0]
    assert env.payload["bin_counts"] == [10, 20, 5]


@pytest.mark.unit
def test_silo_bar_resource_returns_6_silos(six_silos):
    for i in range(1, 7):
        resource_service.ingest_sample(
            ResourceSample(
                silo_id=f"silo-{i}",
                cpu_pct=10.0 * i,
                mem_pct=20.0,
                timestamp="2026-05-14T00:00:00Z",
            )
        )

    env = visualization_service.silo_bar_resource_usage(metric="cpu_pct")

    items = env.payload["items"]
    assert len(items) == 6
    assert {it["silo_id"] for it in items} == {f"silo-{i}" for i in range(1, 7)}
    by_silo = {it["silo_id"]: it["value"] for it in items}
    assert by_silo["silo-1"] == 10.0
    assert by_silo["silo-6"] == 60.0


@pytest.mark.unit
def test_silo_bar_round_returns_contribution_per_silo(six_silos, alpha_model):
    silo_group_service.create_group(
        SiloGroupRequest(group_id="g1", member_node_ids=[f"silo-{i}" for i in range(1, 7)])
    )
    rnd = training_round_service.create_round(
        TrainingRoundCreate(
            model_name="alpha", version="1.0.0", group_id="g1", min_contributions=2
        )
    )
    for i, samples in enumerate((100, 200, 150), start=1):
        training_round_service.submit_contribution(
            ParameterContribution(
                round_id=rnd.round_id,
                silo_id=f"silo-{i}",
                sample_count=samples,
                parameters=[1.0],
            )
        )

    env = visualization_service.silo_bar_round_contributions(rnd.round_id)

    items = env.payload["items"]
    by_silo = {it["silo_id"]: it["value"] for it in items}
    assert by_silo == {"silo-1": 100.0, "silo-2": 200.0, "silo-3": 150.0}


@pytest.mark.unit
def test_heatmap_dimensions_match_silos_and_metrics(six_silos, alpha_model):
    for i in (1, 2, 3):
        _push(f"silo-{i}", "accuracy", 0.5 + 0.1 * i)
        _push(f"silo-{i}", "latency_ms", 100.0 * i)

    env = visualization_service.heatmap_silo_metric(model_name="alpha", version="1.0.0")

    payload = env.payload
    assert payload["row_labels"] == ["silo-1", "silo-2", "silo-3"]
    assert payload["col_labels"] == ["accuracy", "latency_ms", "throughput_rps"]
    # 3행 × 3열
    assert len(payload["matrix"]) == 3
    assert all(len(row) == 3 for row in payload["matrix"])
    # throughput_rps 미수집 → None
    assert payload["matrix"][0][2] is None
    # accuracy/latency 평균 검증
    assert payload["matrix"][0][0] == pytest.approx(0.6)
    assert payload["matrix"][0][1] == pytest.approx(100.0)


@pytest.mark.unit
def test_topology_includes_silos_groups_and_running_deployment(six_silos, alpha_model):
    silo_group_service.create_group(
        SiloGroupRequest(group_id="east", member_node_ids=["silo-1", "silo-2"])
    )
    silo_group_service.create_group(
        SiloGroupRequest(group_id="west", member_node_ids=["silo-3"])
    )
    # 압박 사일로
    resource_service.set_limit(ResourceLimit(silo_id="silo-1", cpu_pct_max=80.0))
    resource_service.ingest_sample(
        ResourceSample(silo_id="silo-1", cpu_pct=95.0, mem_pct=10.0, timestamp="2026-05-14T00:00:00Z")
    )
    # 배포
    fake = MagicMock()
    container = MagicMock()
    container.id = "cid"
    fake.containers.create.return_value = container
    fake.containers.get.return_value = container
    fake.images.get.return_value = MagicMock()
    with patch("services.deployment_service.get_docker_client", return_value=fake):
        deployment_service.create_deployment(
            DeploymentRequest(
                model_name="alpha",
                version="1.0.0",
                strategy="realtime",
                target_node_ids=["silo-2"],
            )
        )

    env = visualization_service.topology()
    payload = env.payload

    node_ids = {n["id"] for n in payload["nodes"]}
    # 6 사일로 + 2 그룹 + 1 배포 = 9 노드
    assert "silo-1" in node_ids
    assert "group::east" in node_ids
    assert any(n.startswith("deploy::") for n in node_ids)

    # 압박 노드 표시
    silo1 = next(n for n in payload["nodes"] if n["id"] == "silo-1")
    assert silo1["over_budget"] is True

    # 엣지 종류 — 집계자 있는 클러스터가 없으므로 aggregation 간선 없음
    kinds = {e["kind"] for e in payload["edges"]}
    assert kinds == {"group", "deployment"}
    assert {n["role"] for n in payload["nodes"] if n["id"].startswith("silo-")} == {"client"}


@pytest.mark.unit
def test_topology_two_tier_cluster_has_aggregation_edges(six_silos):
    """루트 그룹 [silo-1, silo-2] + 엣지 클러스터(집계자 silo-2 → silo-3, silo-4)"""
    silo_group_service.create_group(
        SiloGroupRequest(group_id="root", member_node_ids=["silo-1", "silo-2"])
    )
    silo_group_service.create_group(
        SiloGroupRequest(
            group_id="l3-edge",
            member_node_ids=["silo-3", "silo-4"],
            aggregator_node_id="silo-2",
        )
    )

    payload = visualization_service.topology().payload

    roles = {n["id"]: n["role"] for n in payload["nodes"]}
    assert roles["silo-2"] == "aggregator"
    assert roles["silo-1"] == roles["silo-3"] == "client"

    aggregation = [e for e in payload["edges"] if e["kind"] == "aggregation"]
    assert sorted((e["source"], e["target"]) for e in aggregation) == [
        ("silo-2", "silo-3"),
        ("silo-2", "silo-4"),
    ]
    assert all(e["metadata"] == {"group_id": "l3-edge"} for e in aggregation)
    # 그룹 간선은 그대로 — 클러스터 그룹 노드도 멤버로 이어진다
    group_edges = {(e["source"], e["target"]) for e in payload["edges"] if e["kind"] == "group"}
    assert ("group::l3-edge", "silo-3") in group_edges
    assert ("group::root", "silo-2") in group_edges


# ---------- 참여 매트릭스 (사일로 × 라운드) ----------


def _round(group_id: str, *, min_contributions: int = 1):
    return training_round_service.create_round(
        TrainingRoundCreate(
            model_name="alpha",
            version="1.0.0",
            group_id=group_id,
            min_contributions=min_contributions,
        )
    )


def _contribute(round_id: str, silo_id: str, samples: int, aggregated_from=()) -> None:
    training_round_service.submit_contribution(
        ParameterContribution(
            round_id=round_id,
            silo_id=silo_id,
            sample_count=samples,
            parameters=[1.0],
            aggregated_from=list(aggregated_from),
        )
    )


def _cells(payload: dict, silo_id: str) -> list[tuple]:
    i = payload["row_labels"].index(silo_id)
    return list(zip(payload["matrix"][i], payload["cell_status"][i]))


def _two_tier(cluster_members: list[str]) -> None:
    silo_group_service.create_group(
        SiloGroupRequest(group_id="root", member_node_ids=["silo-1", "silo-2"])
    )
    silo_group_service.create_group(
        SiloGroupRequest(
            group_id="l3-edge",
            member_node_ids=cluster_members,
            aggregator_node_id="silo-2",
        )
    )


@pytest.mark.unit
def test_participation_all_six_silos_contributed(six_silos, alpha_model):
    silo_group_service.create_group(
        SiloGroupRequest(group_id="g6", member_node_ids=[f"silo-{i}" for i in range(1, 7)])
    )
    rnd = _round("g6")
    for i in range(1, 7):
        _contribute(rnd.round_id, f"silo-{i}", 100 * i)
    training_round_service.aggregate_round(rnd.round_id)

    env = visualization_service.heatmap_participation()

    assert env.chart_type == "heatmap"
    assert (env.x_axis, env.y_axis) == ("round", "silo_id")
    payload = env.payload
    assert payload["row_labels"] == [f"silo-{i}" for i in range(1, 7)]
    assert payload["col_labels"] == [rnd.round_id[:8]]
    assert payload["col_meta"] == [
        {
            "round_id": rnd.round_id,
            "status": "completed",
            "created_at": rnd.created_at,
            "group_id": "g6",
        }
    ]
    assert payload["matrix"] == [[100.0 * i] for i in range(1, 7)]
    assert payload["cell_status"] == [["contributed"]] * 6


@pytest.mark.unit
def test_participation_missing_silo_in_completed_round(six_silos, alpha_model):
    silo_group_service.create_group(
        SiloGroupRequest(group_id="g6", member_node_ids=[f"silo-{i}" for i in range(1, 7)])
    )
    rnd = _round("g6", min_contributions=2)
    for i in range(1, 6):
        _contribute(rnd.round_id, f"silo-{i}", 100)
    training_round_service.aggregate_round(rnd.round_id)

    payload = visualization_service.heatmap_participation().payload

    assert _cells(payload, "silo-6") == [(None, "missing")]
    assert _cells(payload, "silo-5") == [(100.0, "contributed")]


@pytest.mark.unit
def test_participation_via_aggregator(six_silos, alpha_model):
    """집계자 silo-2가 클러스터 멤버 2곳 중 silo-3만 대리 제출 → silo-4는 missing"""
    _two_tier(["silo-3", "silo-4"])
    rnd = _round("root", min_contributions=2)
    _contribute(rnd.round_id, "silo-1", 500)
    _contribute(rnd.round_id, "silo-2", 1100, aggregated_from=["silo-3"])
    training_round_service.aggregate_round(rnd.round_id)

    payload = visualization_service.heatmap_participation().payload

    # 행 = 스냅샷(silo-1, silo-2) + 집계자 silo-2의 클러스터 멤버(silo-3, silo-4)
    assert payload["row_labels"] == ["silo-1", "silo-2", "silo-3", "silo-4"]
    assert _cells(payload, "silo-2") == [(1100.0, "contributed")]
    assert _cells(payload, "silo-3") == [(None, "via_aggregator")]
    assert _cells(payload, "silo-4") == [(None, "missing")]


@pytest.mark.unit
def test_participation_open_round_pending_and_column_order(six_silos, alpha_model):
    """완료 라운드(g-a) → 진행 중 라운드(g-b) 순으로 열이 놓이고, 멤버 아닌 칸은 not_member"""
    silo_group_service.create_group(
        SiloGroupRequest(group_id="g-a", member_node_ids=["silo-1", "silo-2"])
    )
    silo_group_service.create_group(
        SiloGroupRequest(group_id="g-b", member_node_ids=["silo-2", "silo-3"])
    )
    with patch.object(
        training_round_service, "_now_iso", return_value="2026-10-06T03:29:13+00:00"
    ):
        old = _round("g-a")
    _contribute(old.round_id, "silo-1", 500)
    training_round_service.aggregate_round(old.round_id)
    with patch.object(
        training_round_service, "_now_iso", return_value="2026-10-06T03:34:13+00:00"
    ):
        new = _round("g-b")
    _contribute(new.round_id, "silo-2", 600)

    payload = visualization_service.heatmap_participation().payload

    assert payload["col_labels"] == [old.round_id[:8], new.round_id[:8]]
    assert [m["status"] for m in payload["col_meta"]] == ["completed", "open"]
    assert payload["row_labels"] == ["silo-1", "silo-2", "silo-3"]
    assert _cells(payload, "silo-1") == [(500.0, "contributed"), (None, "not_member")]
    assert _cells(payload, "silo-2") == [(None, "missing"), (600.0, "contributed")]
    assert _cells(payload, "silo-3") == [(None, "not_member"), (None, "pending")]

    # group_id 필터 + limit(최근 라운드부터 고름)
    only_a = visualization_service.heatmap_participation(group_id="g-a").payload
    assert only_a["col_labels"] == [old.round_id[:8]]
    latest = visualization_service.heatmap_participation(limit=1).payload
    assert latest["col_labels"] == [new.round_id[:8]]


@pytest.mark.unit
def test_participation_open_round_cluster_member_pending(six_silos, alpha_model):
    """진행 중 라운드에서 아직 대리 제출되지 않은 클러스터 멤버는 pending"""
    _two_tier(["silo-3"])
    _round("root")

    payload = visualization_service.heatmap_participation().payload

    assert payload["row_labels"] == ["silo-1", "silo-2", "silo-3"]
    assert payload["cell_status"] == [["pending"], ["pending"], ["pending"]]
    assert payload["matrix"] == [[None], [None], [None]]


@pytest.mark.unit
def test_participation_legacy_round_falls_back_to_current_group(six_silos, alpha_model):
    """member_snapshot 없는 옛 라운드는 현재 그룹 멤버를 행으로 쓴다"""
    silo_group_service.create_group(
        SiloGroupRequest(group_id="g1", member_node_ids=["silo-1", "silo-2"])
    )
    rnd = _round("g1")
    rounds = load_training_rounds()
    legacy = dict(rounds[rnd.round_id])
    legacy.pop("member_snapshot", None)
    rounds[rnd.round_id] = legacy
    save_training_rounds(rounds)

    payload = visualization_service.heatmap_participation().payload

    assert payload["row_labels"] == ["silo-1", "silo-2"]


@pytest.mark.unit
def test_participation_keeps_round_cluster_after_cluster_change(six_silos, alpha_model):
    """라운드 시점 cluster_snapshot 기준 — 이후 클러스터를 바꿔도 이전 라운드 행·상태가 그대로"""
    _two_tier(["silo-3", "silo-4"])
    with patch.object(
        training_round_service, "_now_iso", return_value="2026-10-06T03:29:13+00:00"
    ):
        old = _round("root", min_contributions=2)
    _contribute(old.round_id, "silo-1", 500)
    _contribute(old.round_id, "silo-2", 1100, aggregated_from=["silo-3"])
    training_round_service.aggregate_round(old.round_id)
    before = visualization_service.heatmap_participation().payload

    silo_group_service.update_group(
        "l3-edge",
        SiloGroupRequest(group_id="l3-edge", member_node_ids=["silo-5"], aggregator_node_id="silo-2"),
    )

    assert visualization_service.heatmap_participation().payload == before

    # 변경 뒤 새 라운드는 새 클러스터(silo-5)를 쓴다
    with patch.object(
        training_round_service, "_now_iso", return_value="2026-10-06T03:34:13+00:00"
    ):
        _round("root")
    payload = visualization_service.heatmap_participation().payload
    assert payload["row_labels"] == ["silo-1", "silo-2", "silo-3", "silo-4", "silo-5"]
    assert _cells(payload, "silo-4") == [(None, "missing"), (None, "not_member")]
    assert _cells(payload, "silo-5") == [(None, "not_member"), (None, "pending")]


@pytest.mark.unit
def test_participation_round_without_cluster_snapshot_estimates_current_cluster(
    six_silos, alpha_model
):
    """cluster_snapshot 없는 이전 라운드만 현재 그룹 설정으로 클러스터 멤버를 추정한다"""
    _two_tier(["silo-3", "silo-4"])
    rnd = _round("root")
    rounds = load_training_rounds()
    legacy = dict(rounds[rnd.round_id])
    legacy.pop("cluster_snapshot", None)
    rounds[rnd.round_id] = legacy
    save_training_rounds(rounds)
    silo_group_service.update_group(
        "l3-edge",
        SiloGroupRequest(group_id="l3-edge", member_node_ids=["silo-5"], aggregator_node_id="silo-2"),
    )

    payload = visualization_service.heatmap_participation().payload

    assert payload["row_labels"] == ["silo-1", "silo-2", "silo-5"]


@pytest.mark.unit
def test_participation_no_rounds_returns_empty(six_silos):
    payload = visualization_service.heatmap_participation().payload

    assert payload == {
        "row_labels": [],
        "col_labels": [],
        "col_meta": [],
        "matrix": [],
        "cell_status": [],
    }
