"""수직 통합 — 사일로 안 키 결합(join_sources)과 사일로 간 HMAC 교집합 정렬 (F4)"""
from __future__ import annotations

import hashlib
import hmac

import pytest

from silo_sdk import apply_recipe
from silo_sdk.alignment import align_rows, hash_ids, load_align_key, order_digest
from silo_sdk.integration import CleaningError

KEY = b"0123456789abcdef-shared-silo-key"

JOIN_MAPPING = {
    "key": "id",
    "common_schema": {"id": {"type": "str"}, "x1": {"type": "float"}, "x3": {"type": "float"}},
    "sources": {"p": {"columns": {"rid": "id", "a": "x1"}},
                "e": {"columns": {"eid": "id", "c": "x3"}}},
}
JOIN_STEPS = [
    {"type": "map_schema", "params": {"sources": ["p", "e"]}},
    {"type": "join_sources", "params": {"left": "p", "right": "e", "into": "base"}},
    {"type": "validate_schema", "params": {}},
]


@pytest.mark.unit
def test_join_sources_inner_joins_on_key_and_counts_exclusions():
    tables = {
        "p": [{"rid": "E1", "a": "1"}, {"rid": "E2", "a": "2"}, {"rid": "", "a": "3"},
              {"rid": "E4", "a": "4"}],
        "e": [{"eid": "E2", "c": "5"}, {"eid": "E1", "c": "6"}, {"eid": "E9", "c": "7"}],
    }

    cleaned, counters = apply_recipe(tables, JOIN_STEPS, mapping=JOIN_MAPPING)

    assert cleaned == [{"id": "E1", "x1": 1.0, "x3": 6.0}, {"id": "E2", "x1": 2.0, "x3": 5.0}]
    assert counters["join_sources.in.left"] == 4
    assert counters["join_sources.in.right"] == 3
    assert counters["join_sources.matched"] == 2
    assert counters["join_sources.excluded.left_only"] == 1  # E4
    assert counters["join_sources.excluded.right_only"] == 1  # E9
    assert counters["join_sources.excluded.missing_key"] == 1
    assert counters["join_sources"] == 3


@pytest.mark.unit
def test_join_keeps_left_values_and_fills_from_right():
    tables = {"p": [{"rid": "E1", "a": ""}], "e": [{"eid": "E1", "c": "2"}]}
    steps = [JOIN_STEPS[0], JOIN_STEPS[1]]

    with pytest.raises(CleaningError):  # x1 결측 → 검사하면 유효 행 0
        apply_recipe(tables, [*steps, JOIN_STEPS[2]], mapping=JOIN_MAPPING)
    joined, _ = apply_recipe(tables, steps, mapping=JOIN_MAPPING)
    assert joined[0]["x1"] is None and joined[0]["x3"] == 2.0


@pytest.mark.unit
def test_hash_ids_is_hmac_sha256_and_hides_raw_ids():
    digests = hash_ids(["E00123", "E00124"], KEY)

    expected = hmac.new(KEY, b"E00123", hashlib.sha256).hexdigest()
    assert digests[expected] == "E00123"
    assert all(len(d) == 64 and "E00" not in d for d in digests)
    assert set(hash_ids(["E00123"], b"another-key-0123456789")) != {expected}


@pytest.mark.unit
def test_align_rows_keeps_intersection_in_server_order():
    rows_a = [{"id": f"E{i}", "v": i} for i in (1, 2, 3, 4)]
    rows_b = [{"id": f"E{i}", "v": -i} for i in (5, 3, 2, 6)]
    da, db = hash_ids([r["id"] for r in rows_a], KEY), hash_ids([r["id"] for r in rows_b], KEY)
    intersection = sorted(set(da) & set(db))

    aligned_a, rep_a = align_rows(rows_a, "id", intersection, KEY)
    aligned_b, rep_b = align_rows(rows_b, "id", intersection, KEY)

    assert [r["id"] for r in aligned_a] == [r["id"] for r in aligned_b]
    assert {r["id"] for r in aligned_a} == {"E2", "E3"}
    assert rep_a == {"submitted": 4, "matched": 2, "excluded": 2,
                     "order_digest": order_digest(intersection)}
    assert rep_a["order_digest"] == rep_b["order_digest"]


@pytest.mark.unit
@pytest.mark.parametrize("env", [{}, {"FED_ALIGN_KEY": "short"}])
def test_align_key_must_come_from_silo_env(env):
    with pytest.raises(ValueError, match="FED_ALIGN_KEY"):
        load_align_key(env)


@pytest.mark.unit
def test_align_key_reads_env():
    assert load_align_key({"FED_ALIGN_KEY": KEY.decode()}) == KEY
