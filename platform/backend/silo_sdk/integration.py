"""다원천 통합 정제 — 매핑표로 사일로 원천을 공통 스키마에 맞추고 정합성을 검사한다.

`cleaning.apply_recipe` 가 여러 원천(`{원천 이름: 행 목록}`)을 받으면 이 모듈의 단계를 쓴다.
단계는 표 묶음(tables)을 받아 새 표 묶음과 카운터를 돌려준다. 카운터는 통계만 담는다
(행 수·사유별 건수) — 원시 값은 사일로 밖으로 나가지 않는다.

매핑표(레시피 `mapping`) 형식 — 서버 `models.cleaning_schemas.CleaningMapping` 과 같다:
    key            결합 키 컬럼 (공통 스키마 안)
    common_schema  {컬럼: {type: str|int|float|bool, min?, max?}}
    sources        {원천: {columns: {원천 컬럼: 공통 컬럼}, units: {공통 컬럼: 단위},
                           codes: {공통 컬럼: 코드표}}}
    units          {공통 컬럼: {단위: {scale, offset}}}   변환값 = 값 × scale + offset
    codes          {코드표: {코드: 값}}
표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

Row = dict[str, Any]
Tables = dict[str, list[Row]]
Counters = dict[str, int]


class CleaningError(ValueError):
    """정제 전체 실패 — 레시피·매핑 오류 또는 유효 행 0건. 메시지는 사유 통계만 담는다."""


def load_sources(paths: dict[str, Path]) -> Tables:
    """로컬 원천 파일을 읽는다 — `.json` 은 기록 목록, 그 밖은 CSV(값은 문자열)."""
    tables: Tables = {}
    for name, path in paths.items():
        path = Path(path)
        if path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise CleaningError(f"원천 '{name}': JSON 최상위가 목록이 아닙니다")
            tables[name] = data
        else:
            with path.open(encoding="utf-8", newline="") as f:
                tables[name] = list(csv.DictReader(f))
    return tables


def _bump(counters: Counters, key: str, n: int = 1) -> None:
    counters[key] = counters.get(key, 0) + n


def require_mapping(mapping: dict[str, Any] | None, step_type: str) -> dict[str, Any]:
    if not mapping:
        raise CleaningError(f"'{step_type}' 단계에는 레시피 매핑표(mapping)가 필요합니다")
    return mapping


def source_spec(mapping: dict[str, Any], source: str) -> dict[str, Any]:
    spec = mapping.get("sources", {}).get(source)
    if spec is None:
        raise CleaningError(f"매핑표에 원천 '{source}' 정의가 없습니다")
    return spec


def require_table(tables: Tables, name: str) -> list[Row]:
    if name not in tables:
        raise CleaningError(f"표 '{name}'이(가) 없습니다 (원천 누락 또는 단계 순서 오류)")
    return tables[name]


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def cast_value(value: Any, type_name: str) -> tuple[bool, Any]:
    """공통 스키마 형식으로 변환. (성공 여부, 값) — float은 유한값만 성공."""
    try:
        if type_name == "str":
            return True, str(value).strip()
        if isinstance(value, bool):
            return type_name == "bool", value
        if type_name == "float":
            out = float(value)
            return math.isfinite(out), out
        if type_name == "int":
            as_float = float(value)
            if not as_float.is_integer():
                return False, value
            return True, int(as_float)
        if type_name == "bool":
            if isinstance(value, str):
                return True, value.strip().lower() in {"1", "true", "yes"}
            return True, bool(value)
    except (TypeError, ValueError, OverflowError):
        return False, value
    raise CleaningError(f"지원하지 않는 공통 스키마 형식: {type_name}")


def convert_unit(value: float, column: str, unit: str, mapping: dict[str, Any]) -> float:
    """단위표로 기준 단위 변환 — 값 × scale + offset. 미등록 단위는 KeyError."""
    spec = mapping.get("units", {}).get(column, {})[unit]
    return value * float(spec.get("scale", 1.0)) + float(spec.get("offset", 0.0))


def map_value(
    value: Any, column: str, mapping: dict[str, Any], *,
    unit: str | None = None, code_table: str | None = None,
) -> tuple[Any, str | None]:
    """원천 값 하나를 공통 컬럼 값으로 — 코드표 → 형 변환 → 단위 순.

    반환 (값, 실패 사유). 실패하면 값은 None이고 사유는 code_unmapped·cast_failed·unknown_unit.
    빈 값은 실패가 아니라 결측(None, 사유 없음)이다.
    """
    if _is_blank(value):
        return None, None
    if code_table:
        codes = mapping.get("codes", {}).get(code_table, {})
        key = value.strip() if isinstance(value, str) else value
        if key not in codes:
            return None, "code_unmapped"
        value = codes[key]
    type_name = mapping["common_schema"][column]["type"]
    ok, value = cast_value(value, type_name)
    if not ok:
        return None, "cast_failed"
    if unit:
        try:
            value = convert_unit(value, column, unit, mapping)
        except KeyError:
            return None, "unknown_unit"
    return value, None


def map_schema(tables: Tables, params: dict[str, Any], mapping: dict[str, Any]) -> Counters:
    """표 원천의 컬럼명·형식·단위·코드를 매핑표대로 공통 스키마에 맞춘다 (제자리 갱신).

    매핑에 없는 원천 컬럼은 버리고, 각 행에 `_source`(원천 이름)를 붙인다.
    변환에 실패한 값은 결측(None)으로 두고 사유별로 센다 — 행 제외는 validate_schema 몫.
    """
    counters: Counters = {}
    for source in params["sources"]:
        spec = source_spec(mapping, source)
        if spec.get("format", "table") != "table":
            raise CleaningError(f"원천 '{source}'은 기록 형식입니다 — parse_records를 쓰세요")
        rows = require_table(tables, source)
        units, codes = spec.get("units", {}), spec.get("codes", {})
        mapped: list[Row] = []
        for row in rows:
            new: Row = {}
            for raw_col, col in spec["columns"].items():
                value, failure = map_value(
                    row.get(raw_col), col, mapping,
                    unit=units.get(col), code_table=codes.get(col),
                )
                if failure:
                    _bump(counters, f"map_schema.{failure}")
                new[col] = value
            new["_source"] = source
            mapped.append(new)
        tables[source] = mapped
        _bump(counters, "map_schema", len(mapped))
        _bump(counters, f"map_schema.rows.{source}", len(mapped))
    return counters


def _violation(row: Row, schema: dict[str, Any]) -> str | None:
    if any(row.get(col) is None for col in schema):
        return "missing"
    for col, spec in schema.items():
        value, type_name = row[col], spec["type"]
        if type_name == "float":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif type_name == "int":
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif type_name == "bool":
            ok = isinstance(value, bool)
        else:
            ok = isinstance(value, str)
        if not ok:
            return "type_mismatch"
        if type_name in ("float", "int") and not math.isfinite(value):
            return "non_finite"
        low, high = spec.get("min"), spec.get("max")
        if (low is not None and value < low) or (high is not None and value > high):
            return "out_of_range"
    return None


def validate_schema(rows: list[Row], mapping: dict[str, Any]) -> tuple[list[Row], Counters]:
    """공통 스키마(존재·형식·유한·범위) 위반 행을 제외하고 사유별로 센다.

    통과한 행은 공통 스키마 컬럼만 그 순서대로 남긴다 (`_source` 같은 내부 필드 제거).
    통과한 행이 0건이면 정제 전체 실패로 CleaningError.
    """
    schema = mapping["common_schema"]
    counters: Counters = {}
    kept: list[Row] = []
    for row in rows:
        reason = _violation(row, schema)
        if reason:
            _bump(counters, f"validate_schema.excluded.{reason}")
            continue
        kept.append({col: row[col] for col in schema})
    excluded = len(rows) - len(kept)
    counters["validate_schema"] = excluded
    counters["validate_schema.out"] = len(kept)
    if not kept:
        reasons = {k.rsplit(".", 1)[1]: v for k, v in counters.items() if ".excluded." in k}
        raise CleaningError(
            f"validate_schema: 공통 스키마를 만족하는 행이 없습니다 "
            f"(입력 {len(rows)}행, 사유별 제외 {reasons})"
        )
    return kept, counters


def union_sources(tables: Tables, params: dict[str, Any], mapping: dict[str, Any]) -> Counters:
    """수평 결합 — 공통 스키마에 맞춘 원천들의 행을 이어 붙이고 원천 간·원천 안 중복을 없앤다.

    중복 판정 키는 params.keys(기본 매핑표 key). 키가 비어 있는 행은 중복으로 보지 않고
    남겨 validate_schema가 결측으로 세게 한다. 결과는 params.into 표.
    """
    keys = params.get("keys") or [mapping["key"]]
    counters: Counters = {}
    seen: dict[tuple, str] = {}  # 키 → 처음 본 원천
    combined: list[Row] = []
    for source in params["sources"]:
        rows = require_table(tables, source)
        _bump(counters, f"union_sources.in.{source}", len(rows))
        for row in rows:
            key = tuple(row.get(k) for k in keys)
            if any(_is_blank(v) for v in key):
                combined.append(row)
                continue
            first = seen.get(key)
            if first is not None:
                _bump(counters, f"union_sources.duplicates.{'within' if first == source else 'cross'}")
                continue
            seen[key] = source
            combined.append(row)
    total_in = sum(len(tables[s]) for s in params["sources"])
    tables[params["into"]] = combined
    counters["union_sources.combined"] = total_in
    counters["union_sources"] = total_in - len(combined)
    counters["union_sources.out"] = len(combined)
    return counters


def schema_fingerprint(rows: list[Row]) -> str | None:
    """공통 스키마 지문 — 정렬한 `컬럼:형식` 을 쉼표로 이은 문자열의 sha256.

    컬럼은 행들에 실제로 있는 이름(`_` 로 시작하는 내부 필드 제외), 형식은 값의 파이썬
    형식 이름이다(한 컬럼에 여러 형식이 섞이면 `mixed`). 행이 없으면 None.
    값은 지문에 들어가지 않는다 — 사일로 간 스키마 일치만 비교할 수 있다.
    """
    if not rows:
        return None
    types: dict[str, set[str]] = {}
    for row in rows:
        for col, value in row.items():
            if col.startswith("_"):
                continue
            names = types.setdefault(col, set())
            if value is not None:
                names.add(type(value).__name__)
    parts = []
    for col in sorted(types):
        names = types[col]
        parts.append(f"{col}:{names.pop() if len(names) == 1 else 'mixed' if names else 'null'}")
    return hashlib.sha256(",".join(parts).encode("utf-8")).hexdigest()


def join_sources(tables: Tables, params: dict[str, Any], mapping: dict[str, Any]) -> Counters:
    """사일로 안 수직 결합 — 키 inner join. 결과는 params.into 표.

    왼쪽 값이 우선이고, 왼쪽에 없거나 결측인 컬럼만 오른쪽 값으로 채운다. 오른쪽에 같은 키가
    여러 번 있으면 첫 행을 쓴다. 제외 수를 사유(left_only·right_only·missing_key)별로 센다.
    """
    keys = params.get("keys") or [mapping["key"]]
    left = require_table(tables, params["left"])
    right = require_table(tables, params["right"])
    counters: Counters = {"join_sources.in.left": len(left), "join_sources.in.right": len(right)}
    index: dict[tuple, Row] = {}
    for row in right:
        key = tuple(row.get(k) for k in keys)
        if any(_is_blank(v) for v in key):
            _bump(counters, "join_sources.excluded.missing_key")
            continue
        index.setdefault(key, row)
    joined: list[Row] = []
    used: set[tuple] = set()
    for row in left:
        key = tuple(row.get(k) for k in keys)
        if any(_is_blank(v) for v in key):
            _bump(counters, "join_sources.excluded.missing_key")
            continue
        match = index.get(key)
        if match is None:
            _bump(counters, "join_sources.excluded.left_only")
            continue
        used.add(key)
        merged = dict(row)
        for col, value in match.items():
            if merged.get(col) is None:
                merged[col] = value
        joined.append(merged)
    counters["join_sources.excluded.right_only"] = len(set(index) - used)
    counters["join_sources.matched"] = len(joined)
    counters["join_sources"] = sum(v for k, v in counters.items() if ".excluded." in k)
    tables[params["into"]] = joined
    return counters


# ---------- 교차: JSON 기록 변환 · 충돌 해소 ----------

_SAME_EPS = 1e-6  # 단위 변환 반올림 오차는 같은 값으로 본다


def parse_records(tables: Tables, params: dict[str, Any], mapping: dict[str, Any]) -> Counters:
    """JSON 기록(엔터티·속성 코드·값·단위·시각) → 공통 컬럼 1개짜리 행.

    속성 코드는 매핑표 코드표로, 단위는 단위표로 변환한다(map_schema와 같은 map_value).
    변환에 실패한 기록은 버리고 사유별로 센다. 행에는 `_source`(=into)·`_observed_at`.
    """
    source, into = params["source"], params["into"]
    spec = source_spec(mapping, source)
    if spec.get("format") != "records":
        raise CleaningError(f"원천 '{source}'은 기록 형식이 아닙니다 — map_schema를 쓰세요")
    key = mapping["key"]
    key_field = next((raw for raw, col in spec["columns"].items() if col == key), None)
    if key_field is None:
        raise CleaningError(f"원천 '{source}': 키 '{key}'에 대응하는 필드가 매핑표에 없습니다")
    attr_codes = mapping.get("codes", {}).get(spec.get("attribute_codes") or "", None)
    records = require_table(tables, source)
    counters: Counters = {"parse_records.in": len(records)}
    rows: list[Row] = []

    def fail(reason: str) -> None:
        _bump(counters, "parse_records.conversion_failed")
        _bump(counters, f"parse_records.conversion_failed.{reason}")

    for record in records:
        if not isinstance(record, dict):
            fail("bad_record")
            continue
        entity, failure = map_value(record.get(key_field), key, mapping)
        if entity is None:
            fail(failure or "missing_key")
            continue
        attr = record.get(spec["attribute_field"])
        col = attr_codes.get(attr) if attr_codes is not None else attr
        if col not in mapping["common_schema"] or col == key:
            fail("unknown_code")
            continue
        unit = record.get(spec["unit_field"]) if spec.get("unit_field") else None
        value, failure = map_value(record.get(spec["value_field"]), col, mapping,
                                   unit=None if _is_blank(unit) else str(unit))
        if value is None:
            fail(failure or "missing_value")
            continue
        observed = record.get(spec["time_field"]) if spec.get("time_field") else None
        rows.append({key: entity, col: value, "_source": into, "_observed_at": observed})
    tables[into] = rows
    counters["parse_records"] = counters["parse_records.out"] = len(rows)
    return counters


def _same(values: list[Any]) -> bool:
    first = values[0]
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return all(abs(v - first) <= _SAME_EPS for v in values)
    return all(v == first for v in values)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _resolve(
    cands: list[tuple[Any, int, datetime | None]], tolerance: float
) -> tuple[Any, str | None]:
    """후보 (값, 우선순위, 시각) → (값, 해소 규칙). 규칙은 우선 원천 → 최신 시각 → 허용 오차.

    값이 모두 같으면 규칙 None(충돌 아님). 해소하지 못하면 (None, "unresolved").
    """
    if _same([v for v, _, _ in cands]):
        return cands[0][0], None
    best = min(rank for _, rank, _ in cands)
    if any(rank != best for _, rank, _ in cands):
        cands = [c for c in cands if c[1] == best]
        if _same([v for v, _, _ in cands]):
            return cands[0][0], "priority"
    times = [t for _, _, t in cands if t is not None]
    if len(set(times)) > 1 or (times and len(times) < len(cands)):
        latest = max(times)
        cands = [c for c in cands if c[2] == latest]
        if _same([v for v, _, _ in cands]):
            return cands[0][0], "latest"
    values = [v for v, _, _ in cands]
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        if max(values) - min(values) <= tolerance:
            return sum(values) / len(values), "tolerance"
    return None, "unresolved"


def reconcile(tables: Tables, params: dict[str, Any], mapping: dict[str, Any]) -> Counters:
    """같은 엔터티·속성의 값이 원천마다 다르면 규칙으로 하나를 고른다 (교차 충돌 해소).

    대상 표(target)의 행마다 params.columns 의 후보 = 대상 값 + 다른 원천(sources) 행의 값.
    규칙 순서: 우선 원천(params.priority 앞쪽) → 최신 시각(`_observed_at`) →
    허용 오차(params.tolerance 안이면 평균). 해소하지 못하면 결측(None)으로 두어
    validate_schema가 제외한다. 대상 표에 없는 엔터티의 기록은 orphans로 센다.
    """
    key = mapping["key"]
    target_name = params["target"]
    target = require_table(tables, target_name)
    columns = params["columns"]
    priority = list(params.get("priority") or [target_name])
    tolerance = float(params.get("tolerance", 0.0))

    def rank(name: str) -> int:
        return priority.index(name) if name in priority else len(priority)

    target_keys = {row.get(key) for row in target}
    extra: dict[tuple[Any, str], list[tuple[Any, int, datetime | None]]] = {}
    counters: Counters = {"reconcile.orphans": 0}
    for source in params["sources"]:
        for row in require_table(tables, source):
            if row.get(key) not in target_keys:
                counters["reconcile.orphans"] += 1
                continue
            for col in columns:
                if row.get(col) is not None:
                    extra.setdefault((row[key], col), []).append(
                        (row[col], rank(source), _parse_time(row.get("_observed_at")))
                    )
    out: list[Row] = []
    for row in target:
        new = dict(row)
        for col in columns:
            cands = [(row[col], rank(target_name), None)] if row.get(col) is not None else []
            cands += extra.get((row.get(key), col), [])
            if not cands:
                new[col] = None  # 어느 원천에도 값이 없다 → 결측
                continue
            new[col], rule = _resolve(cands, tolerance)
            if rule:
                _bump(counters, "reconcile.conflicts")
                _bump(counters, "reconcile.unresolved" if rule == "unresolved"
                      else f"reconcile.resolved.{rule}")
        out.append(new)
    tables[params["into"]] = out
    counters["reconcile"] = counters.get("reconcile.conflicts", 0)
    counters.setdefault("reconcile.conflicts", 0)
    counters["reconcile.out"] = len(out)
    return counters
