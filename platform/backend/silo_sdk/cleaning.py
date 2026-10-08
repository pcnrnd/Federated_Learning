"""사일로 측 정제 helper — 로컬 데이터에 레시피 단계를 적용하고 통계만 산출.

원시 데이터는 절대 외부 push 되지 않는다. 본 모듈은 사일로 프로세스 내에서만 동작.
표준 라이브러리만 사용 (사일로 환경 의존성 최소화).

단일 표(행 목록)와 다원천(`{원천 이름: 행 목록}`) 둘 다 받는다. 다원천 단계(매핑·결합·검사)는
`integration` 모듈에 있고, 단일 표 단계는 "현재 표"에 적용된다 — 현재 표는 결과 표를 만드는
단계(`into`)나 `validate_schema`의 `source` 가 정한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from . import integration
from .integration import CleaningError

Row = dict[str, Any]


@dataclass(frozen=True)
class StepCounter:
    step_type: str
    affected: int


def _drop_nulls(rows: list[Row], columns: list[str]) -> tuple[list[Row], int]:
    kept = [r for r in rows if all(r.get(c) is not None and r.get(c) != "" for c in columns)]
    return kept, len(rows) - len(kept)


def _clip_outliers(
    rows: list[Row], column: str, lower: float, upper: float
) -> tuple[list[Row], int]:
    affected = 0
    out: list[Row] = []
    for r in rows:
        v = r.get(column)
        if v is None:
            out.append(r)
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            out.append(r)
            continue
        if f < lower:
            r = {**r, column: lower}
            affected += 1
        elif f > upper:
            r = {**r, column: upper}
            affected += 1
        out.append(r)
    return out, affected


def _dedupe(rows: list[Row], keys: list[str]) -> tuple[list[Row], int]:
    seen: set[tuple] = set()
    kept: list[Row] = []
    for r in rows:
        key = tuple(r.get(k) for k in keys)
        if key in seen:
            continue
        seen.add(key)
        kept.append(r)
    return kept, len(rows) - len(kept)


_CAST_MAP = {
    "int": int,
    "float": float,
    "str": str,
    "bool": lambda v: bool(v) if not isinstance(v, str) else v.lower() in {"1", "true", "yes"},
}


def _cast(rows: list[Row], column: str, to: str) -> tuple[list[Row], int]:
    if to not in _CAST_MAP:
        raise ValueError(f"지원하지 않는 캐스트 타입: {to}")
    fn = _CAST_MAP[to]
    affected = 0
    out: list[Row] = []
    for r in rows:
        v = r.get(column)
        if v is None:
            out.append(r)
            continue
        try:
            new_v = fn(v)
        except (TypeError, ValueError):
            out.append(r)
            continue
        if new_v != v:
            affected += 1
        out.append({**r, column: new_v})
    return out, affected


def _normalize(rows: list[Row], column: str, method: str = "zscore") -> tuple[list[Row], int]:
    values: list[float] = []
    for r in rows:
        v = r.get(column)
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            values.append(0.0)
    if not values:
        return rows, 0
    if method == "minmax":
        lo, hi = min(values), max(values)
        rng = hi - lo or 1.0
        out = [{**r, column: (float(r.get(column, 0)) - lo) / rng} for r in rows]
    else:  # zscore
        mean = sum(values) / len(values)
        var = sum((x - mean) ** 2 for x in values) / len(values) or 1.0
        std = var ** 0.5
        out = [{**r, column: (float(r.get(column, 0)) - mean) / std} for r in rows]
    return out, len(rows)


def _trim_whitespace(rows: list[Row], columns: list[str]) -> tuple[list[Row], int]:
    affected = 0
    out: list[Row] = []
    for r in rows:
        new_r = dict(r)
        changed = False
        for c in columns:
            v = new_r.get(c)
            if isinstance(v, str):
                t = v.strip()
                if t != v:
                    new_r[c] = t
                    changed = True
        if changed:
            affected += 1
        out.append(new_r)
    return out, affected


def _lowercase(rows: list[Row], columns: list[str]) -> tuple[list[Row], int]:
    affected = 0
    out: list[Row] = []
    for r in rows:
        new_r = dict(r)
        changed = False
        for c in columns:
            v = new_r.get(c)
            if isinstance(v, str):
                low = v.lower()
                if low != v:
                    new_r[c] = low
                    changed = True
        if changed:
            affected += 1
        out.append(new_r)
    return out, affected


def _regex_filter(rows: list[Row], column: str, pattern: str) -> tuple[list[Row], int]:
    regex = re.compile(pattern)
    kept = [r for r in rows if isinstance(r.get(column), str) and regex.search(r[column])]
    return kept, len(rows) - len(kept)


_SINGLE_TABLE_STEPS = {
    "drop_nulls": lambda rows, p: _drop_nulls(rows, p["columns"]),
    "clip_outliers": lambda rows, p: _clip_outliers(
        rows, p["column"], float(p["lower"]), float(p["upper"])
    ),
    "dedupe": lambda rows, p: _dedupe(rows, p["keys"]),
    "cast": lambda rows, p: _cast(rows, p["column"], p["to"]),
    "normalize": lambda rows, p: _normalize(rows, p["column"], p.get("method", "zscore")),
    "trim_whitespace": lambda rows, p: _trim_whitespace(rows, p["columns"]),
    "lowercase": lambda rows, p: _lowercase(rows, p["columns"]),
    "regex_filter": lambda rows, p: _regex_filter(rows, p["column"], p["pattern"]),
}
_MULTI_SOURCE_STEPS = ("map_schema", "validate_schema")

# 서버 services.cleaning_recipes.STEP_CATALOG 와 같아야 한다 (테스트로 고정)
SUPPORTED_STEPS = (*_SINGLE_TABLE_STEPS, *_MULTI_SOURCE_STEPS)


def _merge(counters: dict[str, int], extra: dict[str, int]) -> None:
    for key, value in extra.items():
        counters[key] = counters.get(key, 0) + value


def apply_recipe(
    data: Iterable[Row] | dict[str, list[Row]],
    steps: list[dict[str, Any]],
    *,
    mapping: dict[str, Any] | None = None,
) -> tuple[list[Row], dict[str, int]]:
    """레시피 step 리스트를 순차 적용. (cleaned_rows, 카운터) 반환.

    `data` 가 행 목록이면 기존 단일 표 동작 그대로다. `{원천: 행 목록}` 이면 다원천 단계로
    통합한 뒤의 현재 표를 돌려준다. 카운터는 `step_type → 건수` 와 단계별 세부
    (`<step>.<항목>` → 건수)이다. cleaned_rows는 호출자가 로컬에서만 쓴다.

    Raises:
        CleaningError: 매핑표 누락·원천 누락·단계 순서 오류·유효 행 0건 등 정제 전체 실패.
    """
    if isinstance(data, dict):
        tables = {name: list(rows) for name, rows in data.items()}
        current: str | None = None
    else:
        tables, current = {"rows": list(data)}, "rows"
    counters: dict[str, int] = {}
    for step in steps:
        step_type = step["type"]
        params = step.get("params", {})
        if step_type == "map_schema":
            mapping = integration.require_mapping(mapping, step_type)
            _merge(counters, integration.map_schema(tables, params, mapping))
            continue
        if step_type == "validate_schema":
            mapping = integration.require_mapping(mapping, step_type)
            current = params.get("source", current)
            rows = _current(tables, current, step_type)
            tables[current], extra = integration.validate_schema(rows, mapping)
            _merge(counters, extra)
            continue
        if step_type not in _SINGLE_TABLE_STEPS:
            raise ValueError(f"지원하지 않는 step: {step_type}")
        rows = _current(tables, current, step_type)
        tables[current], n = _SINGLE_TABLE_STEPS[step_type](rows, params)
        counters[step_type] = counters.get(step_type, 0) + n
    return _current(tables, current, "결과"), counters


def _current(tables: dict[str, list[Row]], current: str | None, step_type: str) -> list[Row]:
    if current is None:
        raise CleaningError(
            f"'{step_type}' 단계 앞에 결과 표가 정해지지 않았습니다 — 결과 표(into)를 만드는 "
            "단계나 validate_schema의 source가 먼저 와야 합니다"
        )
    return integration.require_table(tables, current)
