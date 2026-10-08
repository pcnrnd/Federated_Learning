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


# ---------- 재검증 전 자체 점검 보완 ----------


@pytest.mark.unit
def test_join_counts_duplicate_right_keys():
    mapping = {"key": "id", "common_schema": {"id": {"type": "str"}, "x": {"type": "float"}},
               "sources": {"l": {"columns": {"k": "id"}}, "r": {"columns": {"k": "id", "v": "x"}}}}
    steps = [{"type": "map_schema", "params": {"sources": ["l", "r"]}},
             {"type": "join_sources", "params": {"left": "l", "right": "r", "into": "j"}},
             {"type": "validate_schema", "params": {}}]
    tables = {"l": [{"k": "E1"}], "r": [{"k": "E1", "v": "1"}, {"k": "E1", "v": "2"}]}

    cleaned, counters = apply_recipe(tables, steps, mapping=mapping)

    assert cleaned == [{"id": "E1", "x": 1.0}]
    assert counters["join_sources.excluded.right_duplicate"] == 1


@pytest.mark.unit
def test_reconcile_treats_float_noise_on_large_values_as_same():
    mapping = {"key": "id", "common_schema": {"id": {"type": "str"}, "x": {"type": "float"}},
               "sources": {"t": {"columns": {"k": "id", "v": "x"}},
                           "s": {"columns": {"k": "id", "v": "x"}}}}
    steps = [{"type": "map_schema", "params": {"sources": ["t", "s"]}},
             {"type": "reconcile", "params": {"target": "t", "sources": ["s"], "columns": ["x"],
                                              "into": "m"}}]
    tables = {"t": [{"k": "E1", "v": "1000000000000.0"}],
              "s": [{"k": "E1", "v": "1000000000000.0001"}]}

    _, counters = apply_recipe(tables, steps, mapping=mapping)

    assert counters["reconcile.conflicts"] == 0


@pytest.mark.unit
def test_load_sources_strips_utf8_bom(tmp_path):
    from silo_sdk.integration import load_sources

    path = tmp_path / "t.csv"
    path.write_bytes("\ufeffeid,x3_level\nE1,L0\n".encode("utf-8"))

    assert load_sources({"t": path})["t"] == [{"eid": "E1", "x3_level": "L0"}]


# ---------- 정수 후보의 동일 판정 (R-F1 N2) ----------

INT_RECON = {
    "key": "id",
    "common_schema": {"id": {"type": "str"}, "x1": {"type": "int"}, "f": {"type": "float"}},
    "sources": {
        "t": {"columns": {"k": "id", "v": "x1", "w": "f"}},
        "r": {"format": "records", "columns": {"eid": "id"}, "attribute_field": "attr",
              "value_field": "value", "time_field": "at"},
    },
}


def _recon(t_rows, records, priority=("facts", "t"), tolerance=0.0, column="x1"):
    steps = [
        {"type": "map_schema", "params": {"sources": ["t"]}},
        {"type": "parse_records", "params": {"source": "r", "into": "facts"}},
        {"type": "reconcile", "params": {"target": "t", "sources": ["facts"], "columns": [column],
                                         "priority": list(priority), "tolerance": tolerance,
                                         "into": "m"}},
    ]
    return apply_recipe({"t": t_rows, "r": records}, steps, mapping=INT_RECON)


@pytest.mark.unit
@pytest.mark.parametrize("a, b", [
    ("1000000000000", "1000000000001"),
    ("9007199254740992", "9007199254740993"),
])
def test_distinct_large_integers_conflict_and_follow_priority(a, b):
    rows, counters = _recon([{"k": "E1", "v": a, "w": "0"}],
                            [{"eid": "E1", "attr": "x1", "value": b, "at": "2026-09-15T00:00:00Z"}])

    assert rows[0]["x1"] == int(b)  # 우선 원천(facts) 값
    assert counters["reconcile.conflicts"] == 1
    assert counters["reconcile.resolved.priority"] == 1


@pytest.mark.unit
def test_equal_large_integers_are_not_a_conflict():
    rows, counters = _recon([{"k": "E1", "v": "9007199254740993", "w": "0"}],
                            [{"eid": "E1", "attr": "x1", "value": "9007199254740993"}])

    assert rows[0]["x1"] == 9007199254740993
    assert counters["reconcile.conflicts"] == 0


@pytest.mark.unit
def test_large_integer_latest_and_unresolved_paths():
    records = [
        {"eid": "E1", "attr": "x1", "value": "9007199254740992", "at": "2026-09-01T00:00:00Z"},
        {"eid": "E1", "attr": "x1", "value": "9007199254740993", "at": "2026-09-15T00:00:00Z"},
        {"eid": "E2", "attr": "x1", "value": "9007199254740992", "at": "2026-09-15T00:00:00Z"},
        {"eid": "E2", "attr": "x1", "value": "9007199254740993", "at": "2026-09-15T00:00:00Z"},
    ]
    rows, counters = _recon([{"k": "E1", "v": "", "w": "0"}, {"k": "E2", "v": "", "w": "0"}],
                            records)
    by_id = {r["id"]: r["x1"] for r in rows}

    assert by_id == {"E1": 9007199254740993, "E2": None}
    assert counters["reconcile.resolved.latest"] == 1
    assert counters["reconcile.unresolved"] == 1


@pytest.mark.unit
def test_float_same_check_allows_rounding_noise_only():
    noise, _ = _recon([{"k": "E1", "v": "1", "w": "1000000000000.0"}],
                      [{"eid": "E1", "attr": "f", "value": "1000000000000.0001"}], column="f")
    distinct, counters = _recon([{"k": "E1", "v": "1", "w": "1000000000000.0"}],
                                [{"eid": "E1", "attr": "f", "value": "1000000000001.0"}],
                                column="f")

    assert noise[0]["f"] == 1000000000000.0
    assert distinct[0]["f"] == 1000000000001.0  # 실제로 다른 값 → 우선 원천
    assert counters["reconcile.conflicts"] == 1


@pytest.mark.unit
def test_integer_tolerance_resolution_stays_an_exact_integer():
    records = [{"eid": "E1", "attr": "x1", "value": "9007199254740993"},
               {"eid": "E1", "attr": "x1", "value": "9007199254740995"}]
    rows, counters = _recon([{"k": "E1", "v": "", "w": "0"}], records, tolerance=2)

    assert rows[0]["x1"] == 9007199254740994 and type(rows[0]["x1"]) is int
    assert counters["reconcile.resolved.tolerance"] == 1


# ---------- 대상 표의 관측 시각 (R-F2 D1) ----------

TIMED = {
    "key": "id",
    "common_schema": {"id": {"type": "str"}, "x1": {"type": "int"}},
    "sources": {
        "ra": {"format": "records", "columns": {"eid": "id"}, "attribute_field": "attr",
               "value_field": "value", "time_field": "at"},
        "rb": {"format": "records", "columns": {"eid": "id"}, "attribute_field": "attr",
               "value_field": "value", "time_field": "at"},
    },
}


def _timed(target_at, older_at):
    steps = [
        {"type": "parse_records", "params": {"source": "ra", "into": "target"}},
        {"type": "parse_records", "params": {"source": "rb", "into": "older"}},
        {"type": "reconcile", "params": {"target": "target", "sources": ["older"],
                                         "columns": ["x1"], "priority": ["preferred"],
                                         "into": "m"}},
        {"type": "validate_schema", "params": {}},
    ]
    tables = {"ra": [{"eid": "E1", "attr": "x1", "value": 20, "at": target_at}],
              "rb": [{"eid": "E1", "attr": "x1", "value": 10, "at": older_at}]}
    return apply_recipe(tables, steps, mapping=TIMED)


@pytest.mark.unit
def test_reconcile_uses_target_observation_time():
    rows, counters = _timed("2026-10-08T00:00:00Z", "2026-10-01T00:00:00Z")

    assert rows == [{"id": "E1", "x1": 20}]  # 대상 값이 더 최신
    assert counters["reconcile.resolved.latest"] == 1


@pytest.mark.unit
def test_reconcile_picks_newer_source_over_older_target():
    rows, counters = _timed("2026-10-01T00:00:00Z", "2026-10-08T00:00:00Z")

    assert rows == [{"id": "E1", "x1": 10}]
    assert counters["reconcile.resolved.latest"] == 1


@pytest.mark.unit
def test_reconcile_output_drops_row_level_time():
    steps = [{"type": "parse_records", "params": {"source": "ra", "into": "target"}},
             {"type": "parse_records", "params": {"source": "rb", "into": "older"}},
             {"type": "reconcile", "params": {"target": "target", "sources": ["older"],
                                              "columns": ["x1"], "into": "m"}}]
    tables = {"ra": [{"eid": "E1", "attr": "x1", "value": 20, "at": "2026-10-08T00:00:00Z"}],
              "rb": [{"eid": "E1", "attr": "x1", "value": 10, "at": "2026-10-09T00:00:00Z"}]}

    rows, _ = apply_recipe(tables, steps, mapping=TIMED)

    assert "_observed_at" not in rows[0]  # 열마다 출처·시각이 달라 행 단위 시각은 남기지 않는다
