"""FedAvg(Federated Averaging) 집계기

가중평균으로 글로벌 파라미터를 산출한다:

    θ_global = Σ (n_k / N) * θ_k

여기서 n_k 는 사일로 k의 로컬 학습 표본수, N 은 모든 사일로 표본수의 합.

원시 데이터는 절대 다루지 않고, 사일로가 사전 계산한 파라미터 벡터만 받는다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _Contribution:
    silo_id: str
    sample_count: int
    parameters: tuple[float, ...]


def aggregate(
    contributions: list[tuple[str, int, list[float]]],
) -> tuple[list[float], int]:
    """샘플수 가중 FedAvg.

    Returns:
        (aggregated_parameters, total_samples)
    """
    if not contributions:
        raise ValueError("기여가 없습니다")

    frozen = [
        _Contribution(silo_id=s, sample_count=n, parameters=tuple(p))
        for s, n, p in contributions
    ]

    dim = len(frozen[0].parameters)
    for c in frozen:
        if len(c.parameters) != dim:
            raise ValueError(
                f"파라미터 차원 불일치: silo={c.silo_id} "
                f"got={len(c.parameters)} expected={dim}"
            )
        if c.sample_count <= 0:
            raise ValueError(f"sample_count는 양수여야 합니다 (silo={c.silo_id})")

    total = sum(c.sample_count for c in frozen)
    aggregated = [0.0] * dim
    for c in frozen:
        weight = c.sample_count / total
        for i, value in enumerate(c.parameters):
            aggregated[i] += weight * value
    return aggregated, total
