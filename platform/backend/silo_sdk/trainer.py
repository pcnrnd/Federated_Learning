"""사일로 측 로컬 학습기 — 순수 파이썬 릿지 회귀 (표준 라이브러리 전용).

정규방정식 (XᵀX + λI)w = Xᵀy 를 가우스 소거로 풀어 닫힌 해를 구한다.
torch 등 외부 의존성이 없어 어떤 사일로 환경에서도 동작한다.

파라미터 평탄화 규약(docs/specs/2026-09-01-state-dict-serialization.md §4):
    parameters = [w_1, ..., w_d, b]   # 편향이 마지막, torch.nn.Linear(d,1)과 동일
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

Row = dict[str, Any]


@dataclass(frozen=True)
class RidgeResult:
    """로컬 릿지 학습 결과 — push_parameters에 그대로 넘길 수 있는 형태"""

    parameters: list[float]  # [w_1..w_d, bias]
    sample_count: int  # 학습에 실제 사용된 행수 (FedAvg 가중치)


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # NaN/Inf는 직렬화 규약상 금지 — 해당 행을 버린다
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """부분 피벗 가우스 소거. 특이 행렬이면 ValueError."""
    n = len(matrix)
    # 증강 행렬 (원본 무변경)
    aug = [list(matrix[i]) + [rhs[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise ValueError(
                "정규방정식이 특이 행렬입니다 — l2를 키우거나 특징을 점검하세요"
            )
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for r in range(col + 1, n):
            factor = aug[r][col] / aug[col][col]
            for c in range(col, n + 1):
                aug[r][c] -= factor * aug[col][c]
    solution = [0.0] * n
    for i in range(n - 1, -1, -1):
        acc = aug[i][n] - sum(aug[i][j] * solution[j] for j in range(i + 1, n))
        solution[i] = acc / aug[i][i]
    return solution


def train_ridge(
    rows: Iterable[Row],
    feature_columns: list[str],
    target_column: str,
    *,
    l2: float = 1e-3,
) -> RidgeResult:
    """로컬 데이터로 릿지 회귀를 학습한다.

    특징·타깃이 숫자로 변환되지 않는 행은 건너뛰며, sample_count에는
    실제 사용된 행수만 담는다. 편향(b)에는 l2 벌점을 주지 않는다.

    Raises:
        ValueError: 특징 미지정, 사용 가능한 행 없음, 정규방정식 특이.
    """
    if not feature_columns:
        raise ValueError("feature_columns가 비어 있습니다")
    if l2 < 0:
        raise ValueError("l2는 0 이상이어야 합니다")

    xs: list[list[float]] = []
    ys: list[float] = []
    for row in rows:
        feats = [_to_float(row.get(c)) for c in feature_columns]
        target = _to_float(row.get(target_column))
        if target is None or any(f is None for f in feats):
            continue
        xs.append([f for f in feats if f is not None])
        ys.append(target)
    if not xs:
        raise ValueError("학습에 사용할 수 있는 행이 없습니다")

    d = len(feature_columns)
    dim = d + 1  # 마지막 열 = 편향 항 (상수 1)
    # 정규방정식 좌변 XᵀX (+ λI, 편향 제외) / 우변 Xᵀy 를 한 번의 순회로 누적
    gram = [[0.0] * dim for _ in range(dim)]
    moment = [0.0] * dim
    for feats, target in zip(xs, ys):
        extended = feats + [1.0]
        for i in range(dim):
            moment[i] += extended[i] * target
            for j in range(dim):
                gram[i][j] += extended[i] * extended[j]
    for i in range(d):  # 편향(dim-1)은 무벌점
        gram[i][i] += l2

    weights = _solve(gram, moment)
    return RidgeResult(parameters=[float(w) for w in weights], sample_count=len(xs))
