"""메트릭 스토어 단위 테스트"""
from __future__ import annotations

import pytest

from models.monitoring_schemas import MetricIngest
from services import metric_store


def _sample(value: float, ts: str = "2026-05-14T00:00:00Z") -> MetricIngest:
    return MetricIngest(
        node_id="silo-2",
        model_name="alpha",
        version="1.0.0",
        metric="accuracy",
        value=value,
        timestamp=ts,
    )


@pytest.mark.unit
def test_ingest_then_query_returns_in_chronological_order():
    metric_store.ingest(_sample(0.9, "2026-05-14T00:00:02Z"))
    metric_store.ingest(_sample(0.8, "2026-05-14T00:00:00Z"))
    metric_store.ingest(_sample(0.95, "2026-05-14T00:00:01Z"))

    results, total = metric_store.query(model_name="alpha", version="1.0.0", metric="accuracy")

    assert total == 3
    assert [s.value for s in results] == [0.8, 0.95, 0.9]


@pytest.mark.unit
def test_query_filters_by_node():
    metric_store.ingest(_sample(0.9))
    other = _sample(0.7).model_copy(update={"node_id": "silo-3"})
    metric_store.ingest(other)

    silo3, total = metric_store.query(node_id="silo-3")

    assert total == 1
    assert len(silo3) == 1
    assert silo3[0].value == 0.7


@pytest.mark.unit
def test_aggregate_returns_mean_min_max_count():
    for v in (0.5, 0.7, 0.9):
        metric_store.ingest(_sample(v))

    agg = metric_store.aggregate(model_name="alpha", version="1.0.0", metric="accuracy")

    assert agg["count"] == 3
    assert agg["min"] == 0.5
    assert agg["max"] == 0.9
    assert agg["mean"] == pytest.approx(0.7)


@pytest.mark.unit
def test_aggregate_empty_does_not_crash():
    agg = metric_store.aggregate(model_name="x", version="1.0.0", metric="accuracy")
    assert agg == {"count": 0, "mean": 0.0, "min": 0.0, "max": 0.0}


@pytest.mark.unit
def test_latest_returns_most_recent_sample():
    metric_store.ingest(_sample(0.5, "2026-05-14T00:00:00Z"))
    metric_store.ingest(_sample(0.6, "2026-05-14T00:00:05Z"))

    latest = metric_store.latest(model_name="alpha", version="1.0.0", metric="accuracy")

    assert latest is not None
    assert latest.value == 0.6
