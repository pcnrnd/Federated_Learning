"""silo_sdk.trainer — 순수 파이썬 릿지 학습기 테스트"""

from __future__ import annotations

import pytest

from silo_sdk.trainer import RidgeResult, train_ridge


def _linear_rows(n: int = 50) -> list[dict]:
    # y = 2*x1 - 3*x2 + 5 (잡음 없음 → l2=0이면 정확 복원)
    rows = []
    for i in range(n):
        x1 = (i % 7) - 3.0
        x2 = (i % 5) * 0.5
        rows.append({"x1": x1, "x2": x2, "y": 2.0 * x1 - 3.0 * x2 + 5.0})
    return rows


def test_잡음_없는_선형관계를_정확히_복원한다():
    result = train_ridge(_linear_rows(), ["x1", "x2"], "y", l2=0.0)

    assert isinstance(result, RidgeResult)
    assert result.sample_count == 50
    w1, w2, bias = result.parameters
    assert w1 == pytest.approx(2.0, abs=1e-8)
    assert w2 == pytest.approx(-3.0, abs=1e-8)
    assert bias == pytest.approx(5.0, abs=1e-8)


def test_평탄화_규약은_가중치_다음_편향_순서다():
    result = train_ridge(_linear_rows(), ["x1", "x2"], "y")
    # [w_1..w_d, b] — 길이 d+1 (직렬화 규약 §4)
    assert len(result.parameters) == 3


def test_l2_양수에서_닫힌형_해와_수치_일치한다():
    # y = x + 10 3점: Σx=0이라 정규방정식이 분리된다 —
    # w = Σxy/(Σx²+λ) = 2/(2+λ), b = ȳ = 10 (편향 무벌점 → 수축 없음)
    rows = [{"x": -1.0, "y": 9.0}, {"x": 0.0, "y": 10.0}, {"x": 1.0, "y": 11.0}]

    result = train_ridge(rows, ["x"], "y", l2=2.0)

    w, b = result.parameters
    assert w == pytest.approx(2.0 / (2.0 + 2.0), abs=1e-12)
    assert b == pytest.approx(10.0, abs=1e-12)


def test_l2가_커지면_가중치가_0으로_수축한다():
    rows = _linear_rows()
    loose = train_ridge(rows, ["x1", "x2"], "y", l2=0.0)
    tight = train_ridge(rows, ["x1", "x2"], "y", l2=1000.0)

    assert abs(tight.parameters[0]) < abs(loose.parameters[0])
    assert abs(tight.parameters[1]) < abs(loose.parameters[1])


def test_숫자가_아닌_행은_건너뛰고_sample_count에서_제외한다():
    rows = _linear_rows(10) + [
        {"x1": None, "x2": 1.0, "y": 1.0},
        {"x1": "abc", "x2": 1.0, "y": 1.0},
        {"x1": 1.0, "x2": 2.0, "y": None},
        {"x1": float("nan"), "x2": 2.0, "y": 1.0},
    ]
    result = train_ridge(rows, ["x1", "x2"], "y", l2=0.0)
    assert result.sample_count == 10


def test_같은_입력이면_같은_결과다():
    a = train_ridge(_linear_rows(), ["x1", "x2"], "y")
    b = train_ridge(_linear_rows(), ["x1", "x2"], "y")
    assert a == b


def test_사용_가능한_행이_없으면_ValueError():
    with pytest.raises(ValueError):
        train_ridge([{"x1": None, "y": 1.0}], ["x1"], "y")


def test_빈_특징_목록은_ValueError():
    with pytest.raises(ValueError):
        train_ridge(_linear_rows(), [], "y")


def test_음수_l2는_ValueError():
    with pytest.raises(ValueError):
        train_ridge(_linear_rows(), ["x1"], "y", l2=-1.0)


def test_중복_특징으로_특이_행렬이면_l2_0에서_ValueError():
    rows = [{"x1": float(i), "x2": float(i), "y": float(i)} for i in range(10)]
    with pytest.raises(ValueError):
        train_ridge(rows, ["x1", "x2"], "y", l2=0.0)
    # 기본 l2(>0)면 풀린다
    result = train_ridge(rows, ["x1", "x2"], "y")
    assert result.sample_count == 10
