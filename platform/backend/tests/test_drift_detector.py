"""드리프트 감지기(PSI) 단위 테스트"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.monitoring_schemas import BaselineRequest, DistributionStats
from services import drift_detector


@pytest.mark.unit
def test_psi_zero_when_distributions_identical():
    counts = [10, 20, 30, 40]
    assert drift_detector.compute_psi(counts, counts) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.unit
def test_psi_positive_when_distributions_differ():
    expected = [100, 100, 100, 100]
    actual = [10, 50, 150, 190]

    psi = drift_detector.compute_psi(expected, actual)

    assert psi > 0


@pytest.mark.unit
def test_classify_severity_thresholds():
    assert drift_detector.classify(0.05) == "stable"
    assert drift_detector.classify(0.15) == "warning"
    assert drift_detector.classify(0.30) == "critical"


@pytest.mark.unit
def test_detect_drift_requires_baseline():
    stats = DistributionStats(
        node_id="silo-2",
        model_name="alpha",
        version="1.0.0",
        feature="age",
        bin_edges=[0.0, 1.0, 2.0],
        bin_counts=[1, 1],
        timestamp="2026-05-14T00:00:00Z",
    )

    with pytest.raises(HTTPException) as exc:
        drift_detector.detect_drift(stats)
    assert exc.value.status_code == 404


@pytest.mark.unit
def test_detect_drift_critical_when_distribution_far_from_baseline():
    drift_detector.set_baseline(
        BaselineRequest(
            model_name="alpha",
            version="1.0.0",
            feature="age",
            bin_edges=[0.0, 10.0, 20.0, 30.0, 40.0],
            bin_counts=[100, 100, 100, 100],
        )
    )
    stats = DistributionStats(
        node_id="silo-2",
        model_name="alpha",
        version="1.0.0",
        feature="age",
        bin_edges=[0.0, 10.0, 20.0, 30.0, 40.0],
        bin_counts=[10, 50, 150, 190],
        timestamp="2026-05-14T00:00:00Z",
    )

    report = drift_detector.detect_drift(stats)

    assert report.severity == "critical"
    assert report.psi > 0.25
    assert report.baseline_total == 400
    assert report.current_total == 400


@pytest.mark.unit
def test_detect_drift_bin_mismatch_returns_400():
    drift_detector.set_baseline(
        BaselineRequest(
            model_name="alpha",
            version="1.0.0",
            feature="age",
            bin_edges=[0.0, 1.0, 2.0],
            bin_counts=[1, 1],
        )
    )
    stats = DistributionStats(
        node_id="silo-2",
        model_name="alpha",
        version="1.0.0",
        feature="age",
        bin_edges=[0.0, 1.0, 2.0, 3.0],
        bin_counts=[1, 1, 1],
        timestamp="2026-05-14T00:00:00Z",
    )

    with pytest.raises(HTTPException) as exc:
        drift_detector.detect_drift(stats)
    assert exc.value.status_code == 400
