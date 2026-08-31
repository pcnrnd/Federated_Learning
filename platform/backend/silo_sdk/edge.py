"""엣지(로컬) 집계 — 사일로 집계자가 하위 노드 파라미터를 로컬에서 가중평균한다.

FedAvg는 결합법칙이 성립하므로 중앙의 집계 수학은 변경할 필요가 없다:

    Σ(n_k/N)·θ_k  =  Σ(N_c/N)·[Σ(n_k/N_c)·θ_k]
    평면 집계              엣지 집계 후 글로벌 집계

`services.fedavg_aggregator.aggregate`와 동일한 수식이지만, 사일로 측에서
표준 라이브러리만으로 동작해야 하므로(SDK 규약) 여기에 별도로 둔다.

사용 흐름:
    total, params = combine(children)          # 하위 파라미터 로컬 평균
    client.push_parameters(round_id, total, params, aggregated_from=[...])

원시 데이터는 다루지 않는다 — 하위가 이미 계산한 파라미터 벡터만 받는다.
"""
from __future__ import annotations


def combine(children: list[tuple[str, int, list[float]]]) -> tuple[int, list[float]]:
    """하위 (silo_id, sample_count, parameters) → (샘플 합, 가중평균 파라미터).

    Args:
        children: 하위 노드의 (식별자, 로컬 학습 표본수, 평탄화 파라미터 벡터) 목록.

    Returns:
        (sample_sum, weighted_parameters) — 그대로 `push_parameters`의
        `sample_count`/`parameters`로 넘기면 중앙이 평면 기여와 동일하게 처리한다.

    Raises:
        ValueError: 하위가 없거나, 파라미터 차원이 불일치하거나, 표본수가 비양수인 경우.
    """
    if not children:
        raise ValueError("하위 기여가 없습니다")

    dim = len(children[0][2])
    if dim == 0:
        raise ValueError("파라미터 벡터가 비어 있습니다")

    for silo_id, sample_count, parameters in children:
        if len(parameters) != dim:
            raise ValueError(
                f"파라미터 차원 불일치: silo={silo_id} "
                f"got={len(parameters)} expected={dim}"
            )
        if sample_count <= 0:
            raise ValueError(f"sample_count는 양수여야 합니다 (silo={silo_id})")

    total = sum(sample_count for _, sample_count, _ in children)
    combined = [0.0] * dim
    for _, sample_count, parameters in children:
        weight = sample_count / total
        for i, value in enumerate(parameters):
            combined[i] += weight * value
    return total, combined
