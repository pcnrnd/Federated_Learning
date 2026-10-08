"""합성 사일로 원천(silo_sdk.synthetic) — 수평·수직·교차 3유형 로컬 파일 (F1)"""
from __future__ import annotations

import csv
import itertools
import json
from pathlib import Path

import pytest

from silo_sdk import synthetic

TYPES = ("horizontal", "vertical", "cross")


def _read(paths: dict[str, Path]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for name, path in paths.items():
        if path.suffix == ".json":
            out[name] = json.loads(path.read_text(encoding="utf-8"))
        else:
            with path.open(encoding="utf-8", newline="") as f:
                out[name] = list(csv.DictReader(f))
    return out


def _covered(data: dict[str, list[dict]], types: tuple[str, ...]) -> set[str]:
    """주어진 유형의 원천만으로 매핑표를 거쳐 얻을 수 있는 공통 컬럼 집합."""
    mapping = synthetic.HVC_MAPPING
    attr_codes = mapping["codes"]["attr"]
    covered: set[str] = set()
    for kind in types:
        for source in synthetic.SOURCE_TYPES[kind]:
            spec = mapping["sources"][source]
            rows = data[source]
            if spec.get("format") == "records":
                covered |= {spec["columns"][c] for c in spec["columns"]}
                covered |= {
                    attr_codes[r[spec["attribute_field"]]]
                    for r in rows
                    if r[spec["attribute_field"]] in attr_codes
                }
            else:
                header = set(rows[0])
                covered |= {spec["columns"][c] for c in header if c in spec["columns"]}
    return covered


@pytest.fixture
def silo3(tmp_path) -> dict[str, list[dict]]:
    return _read(synthetic.write_sources("silo-3", tmp_path / "silo-3"))


@pytest.mark.unit
def test_writes_three_source_types_as_local_files(tmp_path):
    paths = synthetic.write_sources("silo-1", tmp_path)

    assert set(paths) == {"period_a", "period_b", "entity", "records"}
    assert all(p.is_file() and p.parent == tmp_path for p in paths.values())
    assert {s for kind in TYPES for s in synthetic.SOURCE_TYPES[kind]} == set(paths)


@pytest.mark.unit
def test_common_schema_needs_all_three_types(silo3):
    schema = set(synthetic.COMMON_SCHEMA)
    assert schema == {"id", "x1", "x2", "x3", "y"}

    for size in (1, 2):
        for subset in itertools.combinations(TYPES, size):
            missing = schema - _covered(silo3, subset)
            assert missing, f"{subset}만으로 공통 스키마가 완성되면 안 된다"
    assert _covered(silo3, TYPES) >= schema

    # 유형마다 다른 유형이 주지 않는 컬럼이 있다 — 하나라도 빠지면 스키마가 비게 된다
    for kind in TYPES:
        others = tuple(t for t in TYPES if t != kind)
        assert _covered(silo3, (kind,)) - _covered(silo3, others)


@pytest.mark.unit
def test_period_tables_share_items_under_different_column_names(silo3):
    a, b = silo3["period_a"], silo3["period_b"]
    mapping = synthetic.HVC_MAPPING["sources"]
    assert set(a[0]) != set(b[0])
    mapped_a = {mapping["period_a"]["columns"][c] for c in a[0] if c in mapping["period_a"]["columns"]}
    mapped_b = {mapping["period_b"]["columns"][c] for c in b[0] if c in mapping["period_b"]["columns"]}
    assert mapped_a == mapped_b == {"id", "x1", "y"}

    ids_a = [r["rid"] for r in a]
    ids_b = [r["entity"] for r in b]
    assert len(ids_a) > len(set(ids_a)), "원천 안 중복이 있어야 한다"
    assert set(ids_a) & set(ids_b), "원천 간 중복(기간 겹침)이 있어야 한다"


@pytest.mark.unit
def test_dirty_values_are_injected(silo3):
    x1_raw = [r["feat_1"] for r in silo3["period_a"]]
    assert "" in x1_raw  # 결측
    assert any(v and not _is_number(v) for v in x1_raw)  # 형 변환 불가
    assert any(_is_number(v) and abs(float(v)) > 100 for v in x1_raw)  # 이상치

    levels = {r["x3_level"] for r in silo3["entity"]}
    assert "" in levels and levels - set(synthetic.X3_LEVELS) - {""}, "결측·미등록 코드"

    attrs = {r["attr"] for r in silo3["records"]}
    assert attrs - set(synthetic.HVC_MAPPING["codes"]["attr"]), "미등록 속성 코드"


@pytest.mark.unit
def test_entity_ids_overlap_only_partially(silo3):
    period_ids = {r["rid"] for r in silo3["period_a"]} | {r["entity"] for r in silo3["period_b"]}
    entity_ids = {r["eid"] for r in silo3["entity"]}
    assert period_ids & entity_ids
    assert period_ids - entity_ids, "기간 표에만 있는 id(수직 결합 제외 대상)"
    assert entity_ids - period_ids, "엔터티 표에만 있는 id"


@pytest.mark.unit
def test_records_carry_conflicting_values_for_the_same_entity(silo3):
    by_key: dict[tuple[str, str], list[dict]] = {}
    for r in silo3["records"]:
        by_key.setdefault((r["entity_id"], r["attr"]), []).append(r)
    multi = [rs for rs in by_key.values() if len(rs) > 1]
    assert any(len({r["observed_at"] for r in rs}) > 1 for rs in multi), "시각이 다른 충돌"
    assert any(len({r["observed_at"] for r in rs}) == 1 for rs in multi), "같은 시각 충돌"
    units = {r["unit"] for r in silo3["records"]}
    assert units & set(synthetic.HVC_MAPPING["units"]["x2"]), "다른 단위로 기록"


@pytest.mark.unit
def test_generation_is_seeded_by_silo_number(tmp_path):
    first = synthetic.write_sources("silo-2", tmp_path / "a")
    again = synthetic.write_sources("silo-2", tmp_path / "b")
    other = synthetic.write_sources("silo-4", tmp_path / "c")

    for name in first:
        assert first[name].read_bytes() == again[name].read_bytes()
        assert first[name].read_bytes() != other[name].read_bytes()


@pytest.mark.unit
def test_neighbor_silos_share_some_entities(tmp_path):
    """사일로 간 수직 정렬(F4) 대상 — silo-4·5가 일부 엔터티를 공유한다."""
    s4 = _read(synthetic.write_sources("silo-4", tmp_path / "4"))
    s5 = _read(synthetic.write_sources("silo-5", tmp_path / "5"))
    ids4 = {r["eid"] for r in s4["entity"]}
    ids5 = {r["eid"] for r in s5["entity"]}
    shared = ids4 & ids5
    assert shared and ids4 - shared and ids5 - shared


@pytest.mark.unit
def test_ensure_sources_keeps_existing_files(tmp_path):
    paths = synthetic.ensure_sources("silo-1", tmp_path)
    paths["entity"].write_text("eid,x3_level\nE1,L0\n", encoding="utf-8")

    again = synthetic.ensure_sources("silo-1", tmp_path)

    assert again["entity"].read_text(encoding="utf-8") == "eid,x3_level\nE1,L0\n"


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True
