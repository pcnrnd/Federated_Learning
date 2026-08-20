"""사일로 측 정제 helper — 로컬 데이터에 레시피 단계를 적용하고 통계만 산출.

원시 데이터는 절대 외부 push 되지 않는다. 본 모듈은 사일로 프로세스 내에서만 동작.
표준 라이브러리만 사용 (사일로 환경 의존성 최소화).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

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


def apply_recipe(rows: Iterable[Row], steps: list[dict[str, Any]]) -> tuple[list[Row], dict[str, int]]:
    """레시피 step 리스트를 순차 적용. (cleaned_rows, step_type → affected_count) 반환.

    cleaned_rows는 호출자가 로컬에 저장/사용한다. 외부로 push 되어선 안 된다.
    """
    data: list[Row] = list(rows)
    counters: dict[str, int] = {}
    for step in steps:
        step_type = step["type"]
        params = step.get("params", {})
        if step_type == "drop_nulls":
            data, n = _drop_nulls(data, params["columns"])
        elif step_type == "clip_outliers":
            data, n = _clip_outliers(
                data, params["column"], float(params["lower"]), float(params["upper"])
            )
        elif step_type == "dedupe":
            data, n = _dedupe(data, params["keys"])
        elif step_type == "cast":
            data, n = _cast(data, params["column"], params["to"])
        elif step_type == "normalize":
            data, n = _normalize(data, params["column"], params.get("method", "zscore"))
        elif step_type == "trim_whitespace":
            data, n = _trim_whitespace(data, params["columns"])
        elif step_type == "lowercase":
            data, n = _lowercase(data, params["columns"])
        elif step_type == "regex_filter":
            data, n = _regex_filter(data, params["column"], params["pattern"])
        else:
            raise ValueError(f"지원하지 않는 step: {step_type}")
        counters[step_type] = counters.get(step_type, 0) + n
    return data, counters
