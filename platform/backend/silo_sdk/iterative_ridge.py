"""전역 초기값을 사용하는 유한 step ridge GD (표준 라이브러리 전용).

J(w,b) = sum((x·w+b-y)^2)/(2*n) + l2*sum(w^2)/2.
grad_w = mean((prediction-y)*x) + l2*w, grad_b = mean(prediction-y).
편향은 무벌점. 평탄화 순서는 기존 trainer와 같은 [w_1, ..., w_d, b].
기존 closed-form trainer의 lambda와 비교할 때 lambda_closed = n*l2 이다.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IterativeRidgeResult:
    parameters: list[float]
    sample_count: int
    rows_seen: int
    rows_excluded: int
    initial_objective: float
    objective: float
    steps: int


def _finite(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{label}는 유한해야 합니다")
    return value


def _setting(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}는 유한한 숫자여야 합니다")
    try:
        return _finite(float(value), label)
    except OverflowError as exc:
        raise ValueError(f"{label} 범위 초과") from exc


def _data_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _inputs(rows: Iterable[Mapping[str, Any]], feature_columns: Sequence[str],
            target_column: str) -> tuple[list[list[float]], list[float], int]:
    if isinstance(feature_columns, (str, bytes)) or not feature_columns:
        raise ValueError("서로 다른 feature_columns가 필요합니다")
    if any(not isinstance(c, str) or not c for c in feature_columns):
        raise ValueError("특징 이름은 비어 있지 않은 문자열이어야 합니다")
    if len(set(feature_columns)) != len(feature_columns):
        raise ValueError("중복 특징은 허용하지 않습니다")
    if not isinstance(target_column, str) or not target_column or target_column in feature_columns:
        raise ValueError("타깃은 특징과 다른 이름이어야 합니다")
    try:
        iterator = iter(rows)
    except TypeError as exc:
        raise ValueError("rows는 반복 가능한 로컬 행이어야 합니다") from exc
    xs, ys, seen = [], [], 0
    for row in iterator:
        seen += 1
        if not isinstance(row, Mapping):
            continue
        values = [_data_number(row.get(c)) for c in [*feature_columns, target_column]]
        if any(v is None for v in values):
            continue
        xs.append(values[:-1])
        ys.append(values[-1])
    if not xs:
        raise ValueError("학습에 사용할 수 있는 유한한 행이 없습니다")
    return xs, ys, seen


def _parameters(values: Sequence[float], dimension: int) -> list[float]:
    try:
        parameters = list(values)
    except TypeError as exc:
        raise ValueError("명시적 initial_parameters가 필요합니다") from exc
    if len(parameters) != dimension:
        raise ValueError("파라미터 차원은 특징 수+편향 1이어야 합니다")
    return [_setting(v, "parameter") for v in parameters]


def _loss_and_gradient(xs, ys, parameters, l2):
    n, dimension = len(xs), len(parameters) - 1
    errors = [_finite(math.fsum(x * w for x, w in zip(row, parameters[:-1]))
                      + parameters[-1] - y, "예측 오차") for row, y in zip(xs, ys)]
    penalty = 0.0 if l2 == 0 else l2 * math.fsum(w * w for w in parameters[:-1]) / 2
    objective = _finite(math.fsum(error * error / (2 * n) for error in errors) + penalty, "목적함수")
    gradient = [_finite(math.fsum(error * row[j] / n for error, row in zip(errors, xs))
                        + l2 * parameters[j], "gradient") for j in range(dimension)]
    gradient.append(_finite(math.fsum(error / n for error in errors), "편향 gradient"))
    return objective, gradient


def ridge_objective(rows: Iterable[Mapping[str, Any]], feature_columns: Sequence[str],
                    target_column: str, parameters: Sequence[float], *, l2: float) -> float:
    """같은 유효 행 필터/mean/l2 규약의 목적함수. 원시 행은 반환하지 않는다."""
    regularization = _setting(l2, "l2")
    if regularization < 0:
        raise ValueError("l2는 0 이상이어야 합니다")
    xs, ys, _ = _inputs(rows, feature_columns, target_column)
    initial = _parameters(parameters, len(feature_columns) + 1)
    try:
        return _loss_and_gradient(xs, ys, initial, regularization)[0]
    except (OverflowError, ArithmeticError) as exc:
        raise ValueError("목적함수 계산 범위 초과") from exc


def train_iterative_ridge(rows: Iterable[Mapping[str, Any]], feature_columns: Sequence[str],
                          target_column: str, *, initial_parameters: Sequence[float],
                          l2: float, step_size: float, steps: int) -> IterativeRidgeResult:
    """모든 설정·초기 모델을 명시하고 고정 횟수만 업데이트한다.

    기존 trainer처럼 숫자로 변환되지 않는/결측/NaN/Inf/bool 행은 제외한다.
    sample_count는 실제 유효 행 수. 설정·초기값·계산 중 비유한 결과는 거부한다.
    입력 행과 initial_parameters는 바꾸지 않는다. 임의 데이터의 수렴은 보장하지 않는다.
    """
    regularization, rate = _setting(l2, "l2"), _setting(step_size, "step_size")
    if regularization < 0 or rate <= 0:
        raise ValueError("l2는 0 이상, step_size는 양수여야 합니다")
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise ValueError("steps는 양의 정수여야 합니다")
    xs, ys, seen = _inputs(rows, feature_columns, target_column)
    parameters = _parameters(initial_parameters, len(feature_columns) + 1)
    try:
        initial_objective, gradient = _loss_and_gradient(xs, ys, parameters, regularization)
        objective = initial_objective
        for _ in range(steps):
            parameters = [_finite(p - rate * g, "업데이트") for p, g in zip(parameters, gradient)]
            objective, gradient = _loss_and_gradient(xs, ys, parameters, regularization)
    except (OverflowError, ArithmeticError) as exc:
        raise ValueError("학습 계산 범위 초과") from exc
    return IterativeRidgeResult(parameters=parameters, sample_count=len(xs), rows_seen=seen,
        rows_excluded=seen - len(xs), initial_objective=initial_objective, objective=objective, steps=steps)
