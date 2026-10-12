"""다원천 통합 정제 (silo_sdk.integration) — 매핑·정합성(F2)"""
from __future__ import annotations

import math

import pytest

from silo_sdk import apply_recipe, synthetic
from silo_sdk.integration import CleaningError, load_sources

MAPPING = {
    "key": "id",
    "common_schema": {
        "id": {"type": "str"},
        "x1": {"type": "float", "min": -30.0, "max": 30.0},
        "x3": {"type": "float"},
        "y": {"type": "float"},
    },
    "sources": {
        "a": {"columns": {"rid": "id", "feat": "x1", "lvl": "x3", "out": "y"},
              "units": {"y": "centi"}, "codes": {"x3": "level"}},
    },
    "units": {"y": {"centi": {"scale": 0.01, "offset": 0.0}},
              "x1": {"dx": {"scale": 0.1, "offset": -10.0}}},
    "codes": {"level": {"L0": 0.0, "L1": 2.5}},
}


def _map(rows: list[dict], **extra) -> tuple[list[dict], dict[str, int]]:
    steps = [
        {"type": "map_schema", "params": {"sources": ["a"]}},
        {"type": "validate_schema", "params": {"source": "a"}},
    ]
    return apply_recipe({"a": rows}, steps, mapping={**MAPPING, **extra})


@pytest.mark.unit
def test_map_schema_renames_casts_converts_units_and_codes():
    rows = [{"rid": " E1 ", "feat": "1.5", "lvl": "L1", "out": "250", "extra": "drop"}]

    cleaned, counters = _map(rows)

    assert cleaned == [{"id": "E1", "x1": 1.5, "x3": 2.5, "y": 2.5}]
    assert counters["map_schema"] == 1
    assert counters["map_schema.rows.a"] == 1


@pytest.mark.unit
def test_map_schema_counts_conversion_failures_as_missing():
    rows = [
        {"rid": "E1", "feat": "n/a", "lvl": "L0", "out": "100"},  # 형 변환 불가
        {"rid": "E2", "feat": "1", "lvl": "L9", "out": "100"},  # 미등록 코드
        {"rid": "E3", "feat": "", "lvl": "L0", "out": "100"},  # 결측
        {"rid": "E4", "feat": "2", "lvl": "L0", "out": "100"},
    ]

    cleaned, counters = _map(rows)

    assert [r["id"] for r in cleaned] == ["E4"]
    assert counters["map_schema.cast_failed"] == 1
    assert counters["map_schema.code_unmapped"] == 1
    assert counters["validate_schema.excluded.missing"] == 3


@pytest.mark.unit
def test_validate_schema_excludes_rows_by_reason():
    rows = [
        {"id": "E1", "x1": 1.0, "x3": 0.0, "y": 1.0},
        {"id": "E2", "x1": 99.0, "x3": 0.0, "y": 1.0},  # 범위 밖
        {"id": "E3", "x1": float("nan"), "x3": 0.0, "y": 1.0},  # 유한 아님
        {"id": "E4", "x1": "1.0", "x3": 0.0, "y": 1.0},  # 형식 불일치
        {"id": "E5", "x3": 0.0, "y": 1.0},  # 컬럼 없음
        {"id": "E6", "x1": True, "x3": 0.0, "y": 1.0},  # bool은 float 아님
    ]
    steps = [{"type": "validate_schema", "params": {}}]

    cleaned, counters = apply_recipe(rows, steps, mapping=MAPPING)

    assert [r["id"] for r in cleaned] == ["E1"]
    assert counters["validate_schema"] == 5
    assert counters["validate_schema.excluded.out_of_range"] == 1
    assert counters["validate_schema.excluded.non_finite"] == 1
    assert counters["validate_schema.excluded.type_mismatch"] == 2
    assert counters["validate_schema.excluded.missing"] == 1
    assert counters["validate_schema.out"] == 1


@pytest.mark.unit
def test_validate_schema_projects_to_common_schema_order():
    rows = [{"y": 1.0, "_source": "a", "x3": 0.0, "x1": 1.0, "id": "E1", "note": "x"}]

    cleaned, _ = apply_recipe(rows, [{"type": "validate_schema", "params": {}}], mapping=MAPPING)

    assert list(cleaned[0]) == ["id", "x1", "x3", "y"]


@pytest.mark.unit
def test_validate_schema_raises_when_nothing_survives():
    rows = [{"id": "E1", "x1": 99.0, "x3": 0.0, "y": 1.0}]

    with pytest.raises(CleaningError, match="out_of_range"):
        apply_recipe(rows, [{"type": "validate_schema", "params": {}}], mapping=MAPPING)


@pytest.mark.unit
@pytest.mark.parametrize(
    "steps, mapping, match",
    [
        ([{"type": "validate_schema", "params": {}}], None, "매핑표"),
        ([{"type": "map_schema", "params": {"sources": ["ghost"]}}], MAPPING, "ghost"),
        ([{"type": "map_schema", "params": {"sources": ["a"]}},
          {"type": "dedupe", "params": {"keys": ["id"]}}], MAPPING, "결과 표"),
    ],
)
def test_pipeline_errors_are_reported(steps, mapping, match):
    with pytest.raises(CleaningError, match=match):
        apply_recipe({"a": [{"rid": "E1"}]}, steps, mapping=mapping)


@pytest.mark.unit
def test_unit_conversion_applies_scale_and_offset():
    mapping = {**MAPPING, "sources": {"a": {"columns": {"rid": "id", "feat": "x1"},
                                            "units": {"x1": "dx"}}},
               "common_schema": {"id": {"type": "str"}, "x1": {"type": "float"}}}
    steps = [{"type": "map_schema", "params": {"sources": ["a"]}},
             {"type": "validate_schema", "params": {"source": "a"}}]

    cleaned, _ = apply_recipe({"a": [{"rid": "E1", "feat": "125"}]}, steps, mapping=mapping)

    assert math.isclose(cleaned[0]["x1"], 2.5)


@pytest.mark.unit
def test_legacy_single_table_recipe_is_unchanged():
    rows = [{"id": 1, "age": None}, {"id": 2, "age": 3}, {"id": 2, "age": 3}]
    steps = [{"type": "drop_nulls", "params": {"columns": ["age"]}},
             {"type": "dedupe", "params": {"keys": ["id"]}}]

    cleaned, counters = apply_recipe(rows, steps)

    assert cleaned == [{"id": 2, "age": 3}]
    assert counters == {"drop_nulls": 1, "dedupe": 1}


@pytest.mark.unit
def test_load_sources_reads_csv_and_json(tmp_path):
    paths = synthetic.write_sources("silo-1", tmp_path)

    tables = load_sources(paths)

    assert set(tables) == {"period_a", "period_b", "entity", "records"}
    assert all(isinstance(v, str) for v in tables["entity"][0].values())
    assert isinstance(tables["records"][0], dict) and "attr" in tables["records"][0]


# ---------- 수평: union_sources · 스키마 지문 (F3) ----------

UNION_MAPPING = {
    "key": "id",
    "common_schema": {"id": {"type": "str"}, "x1": {"type": "float"}},
    "sources": {"p1": {"columns": {"rid": "id", "a": "x1"}},
                "p2": {"columns": {"entity": "id", "b": "x1"}}},
}
UNION_STEPS = [
    {"type": "map_schema", "params": {"sources": ["p1", "p2"]}},
    {"type": "union_sources", "params": {"sources": ["p1", "p2"], "into": "all"}},
    {"type": "validate_schema", "params": {}},
]


@pytest.mark.unit
def test_union_sources_combines_rows_and_removes_duplicates():
    tables = {
        "p1": [{"rid": "E1", "a": "1"}, {"rid": "E2", "a": "2"}, {"rid": "E2", "a": "2"}],
        "p2": [{"entity": "E2", "b": "2"}, {"entity": "E3", "b": "3"}],
    }

    cleaned, counters = apply_recipe(tables, UNION_STEPS, mapping=UNION_MAPPING)

    assert [r["id"] for r in cleaned] == ["E1", "E2", "E3"]
    assert counters["union_sources.in.p1"] == 3
    assert counters["union_sources.in.p2"] == 2
    assert counters["union_sources.combined"] == 5
    assert counters["union_sources.duplicates.within"] == 1
    assert counters["union_sources.duplicates.cross"] == 1
    assert counters["union_sources"] == 2
    assert counters["union_sources.out"] == 3


@pytest.mark.unit
def test_union_sources_keeps_rows_with_missing_key_for_validation():
    tables = {"p1": [{"rid": "", "a": "1"}, {"rid": "", "a": "2"}], "p2": [{"entity": "E1", "b": "1"}]}

    cleaned, counters = apply_recipe(tables, UNION_STEPS, mapping=UNION_MAPPING)

    assert [r["id"] for r in cleaned] == ["E1"]
    assert counters["union_sources"] == 0
    assert counters["validate_schema.excluded.missing"] == 2


@pytest.mark.unit
def test_schema_fingerprint_is_sorted_column_type_sha256():
    import hashlib

    from silo_sdk.integration import schema_fingerprint

    rows = [{"y": 1.0, "id": "E1", "x1": 2.0, "_source": "p"}]
    expected = hashlib.sha256("id:str,x1:float,y:float".encode()).hexdigest()

    assert schema_fingerprint(rows) == expected
    assert schema_fingerprint([{"x1": 3.0, "id": "E2", "y": 0.5}]) == expected
    assert schema_fingerprint([{"id": "E1", "x1": 2.0}]) != expected  # 컬럼 누락
    assert schema_fingerprint([{"id": "E1", "x1": "2.0", "y": 1.0}]) != expected  # 형식 다름
    assert schema_fingerprint([]) is None
