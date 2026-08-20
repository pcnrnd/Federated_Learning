"""Prometheus exposition format 테스트"""
from __future__ import annotations

import pytest

from models.monitoring_schemas import MetricIngest
from services import metric_store, prometheus_exporter


@pytest.mark.unit
def test_render_empty_returns_empty_string():
    assert prometheus_exporter.render() == ""


@pytest.mark.unit
def test_render_includes_help_type_and_labels():
    metric_store.ingest(
        MetricIngest(
            node_id="silo-2",
            model_name="alpha",
            version="1.0.0",
            metric="accuracy",
            value=0.95,
            timestamp="2026-05-14T00:00:00Z",
        )
    )

    text = prometheus_exporter.render()

    assert "# HELP fed_model_accuracy" in text
    assert "# TYPE fed_model_accuracy gauge" in text
    assert 'model="alpha"' in text
    assert 'version="1.0.0"' in text
    assert 'node="silo-2"' in text
    assert "0.95" in text


@pytest.mark.unit
def test_render_distinct_help_per_metric():
    metric_store.ingest(
        MetricIngest(
            node_id="silo-2",
            model_name="alpha",
            version="1.0.0",
            metric="accuracy",
            value=0.9,
            timestamp="2026-05-14T00:00:00Z",
        )
    )
    metric_store.ingest(
        MetricIngest(
            node_id="silo-2",
            model_name="alpha",
            version="1.0.0",
            metric="latency_ms",
            value=42.0,
            timestamp="2026-05-14T00:00:01Z",
        )
    )

    text = prometheus_exporter.render()

    # 각 메트릭당 HELP/TYPE 라인이 정확히 1개씩만 나와야 한다
    assert text.count("# HELP fed_model_accuracy") == 1
    assert text.count("# HELP fed_model_latency_ms") == 1
