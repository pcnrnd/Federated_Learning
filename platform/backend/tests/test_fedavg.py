"""FedAvg 집계기 단위 테스트"""
from __future__ import annotations

import random

import pytest

from services import fedavg_aggregator
from silo_sdk import edge


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


# ---------- HFL 결합법칙 (설계 스펙 §2 / §6) ----------


@pytest.mark.unit
def test_hierarchical_equals_flat_associativity_property():
    """결합법칙 property — 평면 집계 == 엣지 집계 후 글로벌 집계.

    Σ(n_k/N)·θ_k == Σ(N_c/N)·[Σ(n_k/N_c)·θ_k]
    무작위 파라미터/샘플수로 50회 반복, 절대 오차 ≤ 1e-9.
    """
    rng = random.Random(20260821)  # 고정 시드 — 실패 재현 가능

    for _ in range(50):
        dim = rng.randint(1, 6)
        flat: list[tuple[str, int, list[float]]] = []
        clusters: list[tuple[str, list[tuple[str, int, list[float]]]]] = []

        for c in range(rng.randint(2, 4)):
            children: list[tuple[str, int, list[float]]] = []
            for k in range(rng.randint(1, 5)):
                child = (
                    f"c{c}-n{k}",
                    rng.randint(1, 1000),
                    [rng.uniform(-100.0, 100.0) for _ in range(dim)],
                )
                children.append(child)
                flat.append(child)
            clusters.append((f"agg-{c}", children))

        flat_params, flat_total = fedavg_aggregator.aggregate(flat)

        # 엣지 집계자가 하위를 로컬 평균해 1건씩 제출한 경우
        edge_contributions = []
        for aggregator_id, children in clusters:
            cluster_total, combined = edge.combine(children)
            edge_contributions.append((aggregator_id, cluster_total, combined))
        hier_params, hier_total = fedavg_aggregator.aggregate(edge_contributions)

        assert hier_total == flat_total
        assert len(hier_params) == dim
        for flat_v, hier_v in zip(flat_params, hier_params):
            assert abs(flat_v - hier_v) <= 1e-9


@pytest.mark.unit
def test_single_child_combine_is_bitwise_identity():
    """하위 0개(=자기 자신만) → 가중치 1.0이라 파라미터가 그대로 보존된다."""
    params = [1.5, -2.25, 3.125]

    total, combined = edge.combine([("silo-1", 7, params)])

    assert total == 7
    assert combined == params


@pytest.mark.unit
def test_flat_and_degenerate_hierarchy_are_bitwise_identical():
    """하위 0개면 계층 경로가 기존 평면 경로와 바이트 단위로 동일하다."""
    contributions = [
        ("silo-1", 90, [10.0, 4.0]),
        ("silo-2", 10, [0.0, 8.0]),
    ]

    flat_params, flat_total = fedavg_aggregator.aggregate(contributions)
    degenerate = []
    for silo_id, samples, params in contributions:
        cluster_total, combined = edge.combine([(silo_id, samples, params)])
        degenerate.append((silo_id, cluster_total, combined))
    hier_params, hier_total = fedavg_aggregator.aggregate(degenerate)

    assert hier_params == flat_params
    assert hier_total == flat_total
