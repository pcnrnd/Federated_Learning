"""교차 통합 — JSON 기록 변환(parse_records)·충돌 해소(reconcile)·전체 수평·수직·교차 레시피 (F5)"""
from __future__ import annotations

import pytest

from silo_sdk import apply_recipe, synthetic, train_ridge
from silo_sdk.integration import CleaningError, load_sources

MAPPING = {
    "key": "id",
    "common_schema": {"id": {"type": "str"}, "x1": {"type": "float"}, "x2": {"type": "float"}},
    "sources": {
        "t": {"columns": {"rid": "id", "a": "x1"}},
        "r": {"format": "records", "columns": {"eid": "id"}, "attribute_field": "attr",
              "attribute_codes": "attr", "value_field": "value", "unit_field": "unit",
              "time_field": "at"},
    },
    "units": {"x1": {"dx": {"scale": 0.1, "offset": -10.0}},
              "x2": {"milli": {"scale": 0.001, "offset": 0.0}}},
    "codes": {"attr": {"A1": "x1", "A2": "x2"}},
}
T0, T1 = "2026-09-01T00:00:00+00:00", "2026-09-15T00:00:00Z"


def _rec(eid, attr, value, unit="", at=T1):
    return {"eid": eid, "attr": attr, "value": value, "unit": unit, "at": at}


def _run(table, records, *, tolerance=0.05, validate=False):
    steps = [
        {"type": "map_schema", "params": {"sources": ["t"]}},
        {"type": "parse_records", "params": {"source": "r", "into": "facts"}},
        {"type": "reconcile", "params": {"target": "t", "sources": ["facts"],
                                         "columns": ["x1", "x2"], "priority": ["t", "facts"],
                                         "tolerance": tolerance, "into": "merged"}},
    ]
    if validate:
        steps.append({"type": "validate_schema", "params": {}})
    return apply_recipe({"t": table, "r": records}, steps, mapping=MAPPING)


@pytest.mark.unit
def test_parse_records_converts_codes_and_units_and_counts_failures():
    records = [
        _rec("E1", "A2", "1500", "milli"),
        _rec("E1", "A1", 125, "dx"),
        _rec("E2", "A9", 1),  # 미등록 속성 코드
        _rec("E2", "A2", "?", "milli"),  # 값 변환 불가
        _rec("E2", "A2", 1, "kelvin"),  # 미등록 단위
        _rec("", "A2", 1, "milli"),  # 키 결측
        "not-a-record",
    ]
    tables = {"r": records}
    steps = [{"type": "parse_records", "params": {"source": "r", "into": "facts"}}]

    rows, counters = apply_recipe(tables, steps, mapping=MAPPING)

    assert rows == [
        {"id": "E1", "x2": 1.5, "_source": "facts", "_observed_at": T1},
        {"id": "E1", "x1": pytest.approx(2.5), "_source": "facts", "_observed_at": T1},
    ]
    assert counters["parse_records.in"] == 7
    assert counters["parse_records.out"] == counters["parse_records"] == 2
    assert counters["parse_records.conversion_failed"] == 5
    for reason in ("unknown_code", "cast_failed", "unknown_unit", "missing_key", "bad_record"):
        assert counters[f"parse_records.conversion_failed.{reason}"] == 1


@pytest.mark.unit
def test_reconcile_applies_priority_then_latest_then_tolerance():
    table = [{"rid": f"E{i}", "a": "1"} for i in range(1, 7)]
    records = [
        _rec("E1", "A1", 130, "dx"),  # x1=3 ≠ 표 1 → 우선 원천(t)
        _rec("E2", "A2", 1000, "milli", T0), _rec("E2", "A2", 2000, "milli", T1),  # 최신
        _rec("E3", "A2", 1000, "milli"), _rec("E3", "A2", 1020, "milli"),  # 허용 오차 안
        _rec("E4", "A2", 1000, "milli"), _rec("E4", "A2", 5000, "milli"),  # 해소 불가
        _rec("E5", "A2", 3000, "milli"), _rec("E5", "A2", "3000.0", "milli"),  # 같은 값
        _rec("E6", "A1", 110, "dx"),  # x1=1 = 표 값 (충돌 아님)
        _rec("E9", "A2", 1000, "milli"),  # 대상 표에 없는 엔터티
    ]

    rows, counters = _run(table, records)
    by_id = {r["id"]: r for r in rows}

    assert by_id["E1"]["x1"] == 1.0
    assert by_id["E2"]["x2"] == 2.0
    assert by_id["E3"]["x2"] == pytest.approx(1.01)
    assert by_id["E4"]["x2"] is None
    assert by_id["E5"]["x2"] == 3.0
    assert by_id["E6"]["x2"] is None  # 후보 없음 → 결측 그대로
    assert counters["reconcile.conflicts"] == counters["reconcile"] == 4
    assert counters["reconcile.resolved.priority"] == 1
    assert counters["reconcile.resolved.latest"] == 1
    assert counters["reconcile.resolved.tolerance"] == 1
    assert counters["reconcile.unresolved"] == 1
    assert counters["reconcile.orphans"] == 1
    assert counters["reconcile.out"] == 6


@pytest.mark.unit
def test_reconcile_fills_missing_target_value_from_records():
    rows, counters = _run([{"rid": "E1", "a": "n/a"}],
                          [_rec("E1", "A1", 150, "dx"), _rec("E1", "A2", 500, "milli")],
                          validate=True)

    assert rows == [{"id": "E1", "x1": pytest.approx(5.0), "x2": 0.5}]
    assert counters["reconcile.conflicts"] == 0


@pytest.mark.unit
def test_unresolved_conflict_is_excluded_by_validation():
    rows, counters = _run(
        [{"rid": "E1", "a": "1"}, {"rid": "E2", "a": "1"}],
        [_rec("E1", "A2", 1000, "milli"), _rec("E1", "A2", 9000, "milli"),
         _rec("E2", "A2", 1000, "milli")],
        validate=True,
    )

    assert [r["id"] for r in rows] == ["E2"]
    assert counters["validate_schema.excluded.missing"] == 1


# ---------- 합성 원천 전체 레시피 ----------


def _silo_tables(tmp_path, silo_id: str = "silo-3") -> dict[str, list]:
    return load_sources(synthetic.write_sources(silo_id, tmp_path / silo_id))


@pytest.mark.unit
def test_hvc_recipe_builds_common_schema_from_three_types(tmp_path):
    cleaned, counters = apply_recipe(_silo_tables(tmp_path), synthetic.HVC_STEPS,
                                     mapping=synthetic.HVC_MAPPING)

    assert cleaned and all(list(r) == list(synthetic.COMMON_SCHEMA) for r in cleaned)
    for key in ("union_sources.duplicates.cross", "union_sources.duplicates.within",
                "join_sources.excluded.left_only", "join_sources.excluded.right_only",
                "parse_records.conversion_failed", "reconcile.resolved.priority",
                "reconcile.resolved.latest", "reconcile.resolved.tolerance",
                "reconcile.unresolved", "validate_schema.excluded.missing",
                "validate_schema.excluded.out_of_range", "map_schema.cast_failed",
                "map_schema.code_unmapped"):
        assert counters.get(key, 0) > 0, key
    assert len({r["id"] for r in cleaned}) == len(cleaned)


@pytest.mark.unit
def test_cleaned_rows_recover_the_true_model(tmp_path):
    cleaned, _ = apply_recipe(_silo_tables(tmp_path), synthetic.HVC_STEPS,
                              mapping=synthetic.HVC_MAPPING)

    result = train_ridge(cleaned, ["x1", "x2", "x3"], "y", l2=1e-6)

    expected = [*synthetic.TRUE_WEIGHTS, synthetic.TRUE_BIAS]
    assert result.parameters == pytest.approx(expected, abs=0.05)
    assert result.sample_count == len(cleaned)


@pytest.mark.unit
@pytest.mark.parametrize("dropped", ["horizontal", "vertical", "cross"])
def test_common_schema_fails_without_any_one_type(tmp_path, dropped):
    tables = _silo_tables(tmp_path)
    for source in synthetic.SOURCE_TYPES[dropped]:
        tables[source] = []  # 그 유형의 원천이 비면

    with pytest.raises(CleaningError, match="공통 스키마를 만족하는 행이 없습니다"):
        apply_recipe(tables, synthetic.HVC_STEPS, mapping=synthetic.HVC_MAPPING)
