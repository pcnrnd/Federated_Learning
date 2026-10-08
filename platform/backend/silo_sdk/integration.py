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
import json
import math
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
