"""R-F1 지적 회귀 — 정수 정밀도(D1)·단위 결과 형식(D2)·위반 기록(D3)·시간대 혼합(D4)"""
from __future__ import annotations

import pytest

from silo_sdk import apply_recipe, synthetic
from silo_sdk.integration import cast_value, map_value

INT_MAPPING = {
    "key": "id",
    "common_schema": {"id": {"type": "str"}, "count": {"type": "int"}},
    "sources": {"a": {"columns": {"k": "id", "v": "count"}, "units": {"count": "x10"}}},
    "units": {"count": {"x10": {"scale": 10, "offset": 0}, "half": {"scale": 0.5, "offset": 0},
                        "one": {"scale": 1, "offset": 0}}},
}
STEPS = [{"type": "map_schema", "params": {"sources": ["a"]}},
         {"type": "validate_schema", "params": {"source": "a"}}]


@pytest.mark.unit
@pytest.mark.parametrize("raw, expected", [
    ("9007199254740993", 9007199254740993),
    (" 9007199254740992 ", 9007199254740992),
    ("3.0", 3),
    ("1e3", 1000),
    (12, 12),
    (4.0, 4),
])
def test_int_cast_preserves_precision(raw, expected):
    ok, value = cast_value(raw, "int")
    assert ok and value == expected and type(value) is int


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["3.5", 2.5, "abc", float("inf"), [1], True])
def test_int_cast_rejects_non_integers(raw):
    assert cast_value(raw, "int")[0] is False


@pytest.mark.unit
def test_large_integer_keys_stay_distinct():
    mapping = {"key": "id", "common_schema": {"id": {"type": "int"}},
               "sources": {"a": {"columns": {"k": "id"}}}}
    rows = [{"k": "9007199254740992"}, {"k": "9007199254740993"}]
    steps = [STEPS[0], {"type": "union_sources", "params": {"sources": ["a"], "into": "u"}},
             {"type": "validate_schema", "params": {}}]

    cleaned, counters = apply_recipe({"a": rows}, steps, mapping=mapping)

    assert [r["id"] for r in cleaned] == [9007199254740992, 9007199254740993]
    assert counters["union_sources"] == 0


@pytest.mark.unit
def test_unit_conversion_keeps_integer_type():
    cleaned, _ = apply_recipe({"a": [{"k": "E1", "v": "2"}]}, STEPS, mapping=INT_MAPPING)

    assert cleaned == [{"id": "E1", "count": 20}]
    assert type(cleaned[0]["count"]) is int


@pytest.mark.unit
def test_unit_conversion_to_non_integer_is_counted_and_excluded():
    mapping = {**INT_MAPPING, "sources": {"a": {"columns": {"k": "id", "v": "count"},
                                               "units": {"count": "half"}}}}
    rows = [{"k": "E1", "v": "3"}, {"k": "E2", "v": "4"}]

    cleaned, counters = apply_recipe({"a": rows}, STEPS, mapping=mapping)

    assert cleaned == [{"id": "E2", "count": 2}]
    assert counters["map_schema.cast_failed"] == 1
    assert counters["validate_schema.excluded.missing"] == 1


@pytest.mark.unit
def test_integer_unit_conversion_is_exact_for_large_values():
    mapping = {**INT_MAPPING, "sources": {"a": {"columns": {"k": "id", "v": "count"},
                                               "units": {"count": "one"}}}}

    cleaned, _ = apply_recipe({"a": [{"k": "E1", "v": "9007199254740993"}]}, STEPS,
                              mapping=mapping)

    assert cleaned[0]["count"] == 9007199254740993


@pytest.mark.unit
@pytest.mark.parametrize("raw", [["A2"], {"a": 1}, ("x",)])
def test_non_scalar_values_fail_conversion(raw):
    assert map_value(raw, "id", {"common_schema": {"id": {"type": "str"}}}) == (
        None, "cast_failed")
    codes = {"common_schema": {"x3": {"type": "float"}}, "codes": {"level": {"L0": 0.0}}}
    assert map_value(raw, "x3", codes, code_table="level") == (None, "code_unmapped")


def _silo3_tables(tmp_path):
    from silo_sdk.integration import load_sources

    return load_sources(synthetic.write_sources("silo-3", tmp_path))


@pytest.mark.unit
@pytest.mark.parametrize("bad", [
    {"entity_id": "E00300", "attr": ["A2"], "value": 1000, "unit": "milli"},
    {"entity_id": ["E00300"], "attr": "A2", "value": 1000, "unit": "milli"},
    {"entity_id": "E00300", "attr": "A2", "value": [1000], "unit": "milli"},
    {"entity_id": "E00300", "attr": "A2", "value": 1000, "unit": ["milli"]},
    {"entity_id": "E00300", "attr": "A2", "value": 1000, "unit": "milli", "observed_at": 5},
])
def test_malformed_record_is_excluded_not_fatal(tmp_path, bad):
    tables = _silo3_tables(tmp_path)
    baseline, base_counters = apply_recipe(tables, synthetic.HVC_STEPS,
                                           mapping=synthetic.HVC_MAPPING)
    tables = _silo3_tables(tmp_path)
    tables["records"].append(bad)

    cleaned, counters = apply_recipe(tables, synthetic.HVC_STEPS, mapping=synthetic.HVC_MAPPING)

    assert len(cleaned) >= len(baseline) - 1
    assert counters["parse_records.in"] == base_counters["parse_records.in"] + 1
    failed = counters["parse_records.conversion_failed"] - base_counters[
        "parse_records.conversion_failed"]
    produced = counters["parse_records.out"] - base_counters["parse_records.out"]
    assert failed + produced == 1


@pytest.mark.unit
def test_naive_and_aware_timestamps_are_compared_as_utc(tmp_path):
    tables = _silo3_tables(tmp_path)
    for rec in tables["records"]:
        if rec["observed_at"] == synthetic.OLDER:
            rec["observed_at"] = "2026-09-01T00:00:00"  # 시간대 없음 → UTC로 본다
    for rec in tables["records"][:5]:
        if rec["observed_at"] == synthetic.LATEST:
            rec["observed_at"] = "2026-09-15T00:00:00Z"

    cleaned, counters = apply_recipe(tables, synthetic.HVC_STEPS, mapping=synthetic.HVC_MAPPING)

    baseline, base = apply_recipe(_silo3_tables(tmp_path / "b"), synthetic.HVC_STEPS,
                                  mapping=synthetic.HVC_MAPPING)
    assert counters["reconcile.resolved.latest"] == base["reconcile.resolved.latest"] > 0
    assert len(cleaned) == len(baseline)


@pytest.mark.unit
def test_server_rejects_units_on_non_numeric_columns():
    from pydantic import ValidationError

    from models.cleaning_schemas import CleaningMapping

    with pytest.raises(ValidationError, match="숫자"):
        CleaningMapping(key="id", common_schema={"id": {"type": "str"}},
                        sources={"a": {"columns": {"k": "id"}, "units": {"id": "x"}}},
                        units={"id": {"x": {"scale": 2}}})
