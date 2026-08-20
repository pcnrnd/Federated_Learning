"""사일로 SDK 정제 helper (apply_recipe) 테스트"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SDK_PARENT = Path(__file__).resolve().parent.parent
if str(SDK_PARENT) not in sys.path:
    sys.path.insert(0, str(SDK_PARENT))

from silo_sdk import apply_recipe  # noqa: E402


@pytest.mark.unit
def test_apply_recipe_drop_nulls_and_dedupe():
    rows = [
        {"id": 1, "age": 30, "name": "a"},
        {"id": 2, "age": None, "name": "b"},
        {"id": 1, "age": 30, "name": "a"},  # 중복
        {"id": 3, "age": 25, "name": "c"},
    ]
    steps = [
        {"type": "drop_nulls", "params": {"columns": ["age"]}},
        {"type": "dedupe", "params": {"keys": ["id"]}},
    ]

    cleaned, counters = apply_recipe(rows, steps)

    # null 1건 제거 + 중복 1건 제거 → 2건 남음
    ids = [r["id"] for r in cleaned]
    assert ids == [1, 3]
    assert counters["drop_nulls"] == 1
    assert counters["dedupe"] == 1


@pytest.mark.unit
def test_apply_recipe_clip_outliers():
    rows = [{"v": v} for v in (0, 50, 100, 999, -50)]
    steps = [
        {
            "type": "clip_outliers",
            "params": {"column": "v", "lower": 0, "upper": 100},
        }
    ]

    cleaned, counters = apply_recipe(rows, steps)

    assert [r["v"] for r in cleaned] == [0, 50, 100, 100, 0]
    assert counters["clip_outliers"] == 2  # 999, -50 변경


@pytest.mark.unit
def test_apply_recipe_lowercase_trim():
    rows = [{"email": "  Foo@Bar.com "}, {"email": "BAZ@QUX.com"}]
    steps = [
        {"type": "trim_whitespace", "params": {"columns": ["email"]}},
        {"type": "lowercase", "params": {"columns": ["email"]}},
    ]

    cleaned, _ = apply_recipe(rows, steps)

    assert cleaned[0]["email"] == "foo@bar.com"
    assert cleaned[1]["email"] == "baz@qux.com"


@pytest.mark.unit
def test_apply_recipe_regex_filter():
    rows = [{"code": "A1"}, {"code": "B2"}, {"code": "BAD"}, {"code": "C3"}]
    steps = [{"type": "regex_filter", "params": {"column": "code", "pattern": r"^[A-C]\d$"}}]

    cleaned, counters = apply_recipe(rows, steps)

    assert [r["code"] for r in cleaned] == ["A1", "B2", "C3"]
    assert counters["regex_filter"] == 1


@pytest.mark.unit
def test_apply_recipe_cast_to_int():
    rows = [{"age": "30"}, {"age": "abc"}, {"age": "45"}]
    steps = [{"type": "cast", "params": {"column": "age", "to": "int"}}]

    cleaned, counters = apply_recipe(rows, steps)

    assert cleaned[0]["age"] == 30
    assert cleaned[1]["age"] == "abc"  # 변환 실패는 원본 유지
    assert cleaned[2]["age"] == 45
    assert counters["cast"] == 2
