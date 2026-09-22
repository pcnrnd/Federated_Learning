"""엣지(로컬) 집계 — 사일로 집계자가 **자신과 하위 노드**의 파라미터를 로컬에서 가중평균한다.

FedAvg는 결합법칙이 성립하므로 중앙의 집계 수학은 변경할 필요가 없다:

    Σ(n_k/N)·θ_k  =  Σ(N_c/N)·[Σ(n_k/N_c)·θ_k]
    평면 집계              엣지 집계 후 글로벌 집계

단, 이 등식은 클러스터 합 N_c 가 **그 클러스터에 속한 모든 데이터 보유자**를 덮을 때만
성립한다. 집계자 사일로는 순수 중계자가 아니라 **자신도 로컬 데이터로 학습하는 사일로**
이므로(`docs/specs/2026-07-24-silo-hierarchy-design.md` §엣지 집계의 참여 범위), 집계자
자신의 기여를 빼면 그 표본이 분자·분모 양쪽에서 사라져 글로벌 파라미터가 평면 집계와
달라진다. 따라서 `combine()` 에 넘기는 목록에는 **집계자 자신이 반드시 포함**된다.

`services.fedavg_aggregator.aggregate`와 동일한 수식이지만, 사일로 측에서
표준 라이브러리만으로 동작해야 하므로(SDK 규약) 여기에 별도로 둔다.

사용 흐름:
    # participants[0] = 집계자 자신의 로컬 학습 결과, 나머지 = 하위 노드들
    total, params = combine([(me, my_n, my_params), *children])
    client.push_parameters(round_id, total, params,
                           aggregated_from=[child_id, ...])  # provenance 는 하위만

원시 데이터는 다루지 않는다 — 각 참여자가 이미 계산한 파라미터 벡터만 받는다.
"""
from __future__ import annotations


def combine(
    participants: list[tuple[str, int, list[float]]],
) -> tuple[int, list[float]]:
    """엣지 참여자 (silo_id, sample_count, parameters) → (표본 합, 가중평균 파라미터).

    Args:
        participants: **집계자 자신 + 하위 노드**의
            (식별자, 로컬 학습 표본수, 평탄화 파라미터 벡터) 목록.
            집계자가 자기 데이터로 학습하지 않는 순수 중계자일 때만 하위만으로 구성된다.

    Returns:
        (sample_sum, weighted_parameters) — `sample_sum` 은 **집계자 자신 + 하위**의
        표본수 합이다. 그대로 `push_parameters`의 `sample_count`/`parameters`로 넘기면
        중앙이 평면 기여와 수치적으로 동일하게 처리한다.
        (`aggregated_from` 은 provenance 이므로 하위 id 만 넘긴다 — 서버가 자기 자신
        포함을 422로 거부한다.)

    Raises:
        ValueError: 참여자가 없거나, 파라미터 차원이 불일치하거나, 표본수가 비양수인 경우.
    """
    if not participants:
        raise ValueError("엣지 참여 기여가 없습니다")

    dim = len(participants[0][2])
    if dim == 0:
        raise ValueError("파라미터 벡터가 비어 있습니다")

    for silo_id, sample_count, parameters in participants:
        if len(parameters) != dim:
            raise ValueError(
                f"파라미터 차원 불일치: silo={silo_id} "
                f"got={len(parameters)} expected={dim}"
            )
        if sample_count <= 0:
            raise ValueError(f"sample_count는 양수여야 합니다 (silo={silo_id})")

    total = sum(sample_count for _, sample_count, _ in participants)
    combined = [0.0] * dim
    for _, sample_count, parameters in participants:
        weight = sample_count / total
        for i, value in enumerate(parameters):
            combined[i] += weight * value
    return total, combined
