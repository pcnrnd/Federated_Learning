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

    **집계자도 자기 로컬 데이터를 가진 사일로**로 모델링한다
    (`docs/specs/2026-07-24-silo-hierarchy-design.md` §엣지 집계의 참여 범위).
    집계자를 데이터 없는 중계자로 두면 이 등식이 "집계자 표본 누락" 결함이 있어도
    성립해버려 테스트가 결함을 원리적으로 잡지 못한다 — 그래서 집계자의 기여를
    평면 목록과 엣지 참여 목록 **양쪽에** 넣고 두 경로가 일치하는지 본다.
    무작위 파라미터/샘플수로 50회 반복, 절대 오차 ≤ 1e-9.
    """
    rng = random.Random(20260821)  # 고정 시드 — 실패 재현 가능

    for _ in range(50):
        dim = rng.randint(1, 6)
        flat: list[tuple[str, int, list[float]]] = []
        clusters: list[tuple[str, list[tuple[str, int, list[float]]]]] = []

        for c in range(rng.randint(2, 4)):
            aggregator_id = f"agg-{c}"
            # 집계자 자신의 로컬 학습 결과 — 엣지 참여 목록의 첫 원소이자 평면의 1건
            own = (
                aggregator_id,
                rng.randint(1, 1000),
                [rng.uniform(-100.0, 100.0) for _ in range(dim)],
            )
            participants: list[tuple[str, int, list[float]]] = [own]
            flat.append(own)
            for k in range(rng.randint(1, 5)):
                child = (
                    f"c{c}-n{k}",
                    rng.randint(1, 1000),
                    [rng.uniform(-100.0, 100.0) for _ in range(dim)],
                )
                participants.append(child)
                flat.append(child)
            clusters.append((aggregator_id, participants))

        flat_params, flat_total = fedavg_aggregator.aggregate(flat)

        # 엣지 집계자가 자신 + 하위를 로컬 평균해 1건씩 제출한 경우
        edge_contributions = []
        for aggregator_id, participants in clusters:
            cluster_total, combined = edge.combine(participants)
            edge_contributions.append((aggregator_id, cluster_total, combined))
        hier_params, hier_total = fedavg_aggregator.aggregate(edge_contributions)

        assert hier_total == flat_total
        assert len(hier_params) == dim
        for flat_v, hier_v in zip(flat_params, hier_params):
            assert abs(flat_v - hier_v) <= 1e-9


@pytest.mark.unit
def test_dropping_aggregator_own_samples_breaks_associativity():
    """회귀 방지 — 집계자 자신을 combine에서 빼면 결합법칙이 실제로 깨진다.

    위 property test가 결함을 잡을 수 있는 테스트인지 자체를 고정한다:
    구 동작(하위만 combine)이 평면 집계와 달라짐을 단언한다.
    """
    own = ("agg", 400, [10.0, 0.0])
    children = [("c1", 500, [0.0, 10.0]), ("c2", 600, [2.0, 2.0])]

    flat_params, flat_total = fedavg_aggregator.aggregate([own, *children])

    # 구 동작: 하위만 combine → 집계자의 400 표본이 분자·분모에서 동시에 사라진다
    buggy_total, buggy_params = edge.combine(children)
    buggy_global, buggy_round_total = fedavg_aggregator.aggregate(
        [("agg", buggy_total, buggy_params)]
    )
    assert buggy_round_total == 1100
    assert buggy_round_total != flat_total
    assert buggy_global != pytest.approx(flat_params)

    # 정정된 동작: 자신 + 하위
    fixed_total, fixed_params = edge.combine([own, *children])
    fixed_global, fixed_round_total = fedavg_aggregator.aggregate(
        [("agg", fixed_total, fixed_params)]
    )
    assert fixed_round_total == flat_total == 1500
    assert fixed_global == pytest.approx(flat_params)


@pytest.mark.unit
def test_l3_two_tier_scenario_totals_3300():
    """L3 실측 시나리오 회귀선 — 2단 HFL 라운드 합계가 3300이어야 한다.

    구성(2026-09-21 L3 / 2026-09-08 HFL과 동일): 루트 silo-1·2·5·6,
    엣지 클러스터 집계자 silo-2 / 멤버 silo-3·4.
    표본수 silo-1=300 … silo-6=800 (`scripts/silo_worker._local_train_rows`).
    구 동작은 집계자 silo-2의 400을 빠뜨려 라운드 합계가 2900이었다.
    """
    samples = {f"silo-{i}": 200 + i * 100 for i in range(1, 7)}
    assert samples["silo-2"] == 400 and sum(samples.values()) == 3300

    def params(silo_id: str) -> list[float]:
        return [float(samples[silo_id]), -float(samples[silo_id]) / 2.0]

    flat = [(sid, n, params(sid)) for sid, n in samples.items()]
    flat_params, flat_total = fedavg_aggregator.aggregate(flat)
    assert flat_total == 3300

    edge_total, edge_params = edge.combine(
        [
            ("silo-2", samples["silo-2"], params("silo-2")),  # 집계자 자신
            ("silo-3", samples["silo-3"], params("silo-3")),
            ("silo-4", samples["silo-4"], params("silo-4")),
        ]
    )
    assert edge_total == 1500  # 구 동작은 1100 (자신 400 누락)

    hier_params, hier_total = fedavg_aggregator.aggregate(
        [
            ("silo-1", samples["silo-1"], params("silo-1")),
            ("silo-2", edge_total, edge_params),
            ("silo-5", samples["silo-5"], params("silo-5")),
            ("silo-6", samples["silo-6"], params("silo-6")),
        ]
    )

    assert hier_total == 3300
    assert hier_params == pytest.approx(flat_params)


@pytest.mark.unit
def test_single_participant_combine_is_bitwise_identity():
    """참여자 1명(=집계자 자신만, 하위 0개) → 가중치 1.0이라 파라미터가 그대로 보존된다."""
    params = [1.5, -2.25, 3.125]

    total, combined = edge.combine([("silo-1", 7, params)])

    assert total == 7
    assert combined == params


@pytest.mark.unit
def test_flat_and_degenerate_hierarchy_are_bitwise_identical():
    """하위 0개면(자신만 combine) 계층 경로가 기존 평면 경로와 바이트 단위로 동일하다."""
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
