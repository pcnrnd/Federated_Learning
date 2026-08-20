"""FedAvg 집계기 단위 테스트"""
from __future__ import annotations

import pytest

from services import fedavg_aggregator


@pytest.mark.unit
def test_simple_average_when_equal_samples():
    contributions = [
        ("silo-1", 10, [0.0, 2.0]),
        ("silo-2", 10, [2.0, 0.0]),
    ]

    aggregated, total = fedavg_aggregator.aggregate(contributions)

    assert aggregated == [1.0, 1.0]
    assert total == 20


@pytest.mark.unit
def test_weighted_by_sample_count():
    # silo-1이 90% 가중치
    contributions = [
        ("silo-1", 90, [10.0]),
        ("silo-2", 10, [0.0]),
    ]

    aggregated, total = fedavg_aggregator.aggregate(contributions)

    assert aggregated[0] == pytest.approx(9.0)
    assert total == 100


@pytest.mark.unit
def test_dimension_mismatch_raises():
    contributions = [
        ("silo-1", 1, [1.0, 2.0]),
        ("silo-2", 1, [1.0]),
    ]
    with pytest.raises(ValueError, match="차원 불일치"):
        fedavg_aggregator.aggregate(contributions)


@pytest.mark.unit
def test_zero_sample_count_rejected():
    with pytest.raises(ValueError):
        fedavg_aggregator.aggregate([("silo-1", 0, [1.0])])


@pytest.mark.unit
def test_empty_contributions_rejected():
    with pytest.raises(ValueError):
        fedavg_aggregator.aggregate([])
