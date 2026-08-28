"""시각화 5종 차트 데이터 단위 테스트"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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

    # 엣지 종류
    kinds = {e["kind"] for e in payload["edges"]}
    assert kinds == {"group", "deployment"}
