"""합성 사일로 원천 — 데모·E2E용 로컬 파일 생성 (표준 라이브러리 전용).

사일로마다 원천 3유형을 로컬 파일로 만든다 (시드 = 사일로 번호, 같은 사일로는 늘 같은 파일):
  * 수평 — 기간별 표 2개 `period_a.csv`·`period_b.csv`: 같은 항목(id·x1·y)인데 컬럼명이
    서로 다르고 period_b의 y는 1/100 단위다. 두 기간이 일부 겹쳐 원천 간 중복이 생긴다.
  * 수직 — 엔터티 속성 표 `entity.csv`: `eid` 키로 x3(수준 코드 L0~L4)을 준다.
    기간 표와 id가 일부만 겹친다(한쪽에만 있는 id가 양쪽에 있다).
  * 교차 — JSON 기록 `records.json`: 같은 엔터티의 속성을 다른 단위·속성 코드로 기록한다.
    x2는 여기에만 있고, x1은 기간 표와 겹쳐 값이 어긋나는 충돌원이 된다.

공통 스키마 `id, x1, x2, x3, y` 는 세 유형을 모두 통합해야만 완성된다
(y = 기간 표만, x3 = 엔터티 표만, x2 = JSON 기록만). 결측·이상치·중복·형 변환 불가 값·
미등록 코드·같은 엔터티의 충돌 기록을 의도적으로 섞는다. 참 모델은 기존 학습 데이터와 같다:
    y = 2·x1 − 3·x2 + 0.5·x3 + 4 + 잡음

`HVC_MAPPING` 은 이 원천을 공통 스키마로 정제하는 레시피의 매핑표다.
원천 파일은 사일로 밖으로 나가지 않는다 — 중앙에는 레시피만 있고 결과는 통계로만 보고한다.
"""
from __future__ import annotations

import csv
import json
import random
from pathlib import Path
from typing import Any

TRUE_WEIGHTS = (2.0, -3.0, 0.5)
TRUE_BIAS = 4.0
COMMON_SCHEMA = ("id", "x1", "x2", "x3", "y")

SOURCE_FILES = {
    "period_a": "period_a.csv",
    "period_b": "period_b.csv",
    "entity": "entity.csv",
    "records": "records.json",
}
SOURCE_TYPES = {
    "horizontal": ("period_a", "period_b"),
    "vertical": ("entity",),
    "cross": ("records",),
}
X3_LEVELS = {"L0": 0.0, "L1": 2.5, "L2": 5.0, "L3": 7.5, "L4": 10.0}

OLDER, LATEST = "2026-09-01T00:00:00+00:00", "2026-09-15T00:00:00+00:00"

HVC_MAPPING: dict[str, Any] = {
    "key": "id",
    "common_schema": {
        "id": {"type": "str"},
        "x1": {"type": "float", "min": -30.0, "max": 30.0},
        "x2": {"type": "float", "min": -60.0, "max": 60.0},
        "x3": {"type": "float", "min": 0.0, "max": 10.0},
        "y": {"type": "float"},
    },
    "sources": {
        "period_a": {"columns": {"rid": "id", "feat_1": "x1", "target": "y"}},
        "period_b": {
            "columns": {"entity": "id", "f1": "x1", "outcome_c": "y"},
            "units": {"y": "centi"},
        },
        "entity": {"columns": {"eid": "id", "x3_level": "x3"}, "codes": {"x3": "level"}},
        "records": {
            "format": "records",
            "columns": {"entity_id": "id"},
            "attribute_field": "attr",
            "attribute_codes": "attr",
            "value_field": "value",
            "unit_field": "unit",
            "time_field": "observed_at",
        },
    },
    "units": {
        "y": {"centi": {"scale": 0.01, "offset": 0.0}},
        # JSON 기록의 x1 = (x1 + 10) × 10 → 배율 0.1, 오프셋 −10
        "x1": {"dx": {"scale": 0.1, "offset": -10.0}},
        "x2": {"milli": {"scale": 0.001, "offset": 0.0}},
    },
    "codes": {"level": dict(X3_LEVELS), "attr": {"A1": "x1", "A2": "x2"}},
}


def seed_of(silo_id: str) -> int:
    digits = "".join(ch for ch in silo_id if ch.isdigit())
    return int(digits) if digits else 7


def _entities(seed: int, rng: random.Random) -> list[dict[str, Any]]:
    """참값 엔터티 — 사일로마다 표본수·특징 분포가 다르다 (non-IID)."""
    n = 200 + seed * 100  # silo-1=300 … silo-6=800
    start = seed * 100  # 이웃 사일로와 id가 일부 겹친다 (사일로 간 수직 정렬 대상)
    shift = (seed - 2) * 1.5
    out: list[dict[str, Any]] = []
    for k in range(n):
        level = rng.choice(list(X3_LEVELS))
        x1 = round(rng.gauss(shift, 1.0), 6)
        x2 = round(rng.gauss(-shift, 2.0), 6)
        x3 = X3_LEVELS[level]
        y = TRUE_WEIGHTS[0] * x1 + TRUE_WEIGHTS[1] * x2 + TRUE_WEIGHTS[2] * x3 + TRUE_BIAS
        out.append({"id": f"E{start + k:05d}", "x1": x1, "x2": x2, "level": level,
                    "y": round(y + rng.gauss(0.0, 0.1), 6)})
    return out


def _dirty_x1(rng: random.Random, x1: float) -> str:
    roll = rng.random()
    if roll < 0.03:
        return ""  # 결측
    if roll < 0.04:
        return "n/a"  # 형 변환 불가
    if roll < 0.06:
        return "999.0"  # 이상치
    return repr(x1)


def _period_rows(ents: list[dict[str, Any]], rng: random.Random) -> tuple[list, list]:
    n = len(ents)
    a_part, b_part = ents[: int(n * 0.6)], ents[int(n * 0.5):]  # 10% 기간 겹침
    period_a = [
        {"rid": e["id"], "feat_1": _dirty_x1(rng, e["x1"]), "target": repr(e["y"]),
         "period": "2026Q1"}
        for e in a_part
    ]
    period_a += [dict(period_a[i]) for i in range(0, len(period_a), 20)]  # 원천 안 중복
    rng.shuffle(period_a)
    period_b = [
        {"entity": e["id"], "f1": _dirty_x1(rng, e["x1"]),
         "outcome_c": repr(round(e["y"] * 100, 4)), "period": "2026Q2"}
        for e in b_part
    ]
    return period_a, period_b


def _entity_rows(ents: list[dict[str, Any]], seed: int, rng: random.Random) -> list[dict]:
    n = len(ents)
    rows: list[dict[str, str]] = []
    for e in ents[int(n * 0.05):]:  # 앞 5%는 엔터티 표에 없다 (기간 표에만 있는 id)
        roll = rng.random()
        level = "" if roll < 0.02 else "L9" if roll < 0.03 else e["level"]
        rows.append({"eid": e["id"], "x3_level": level})
    extra_start = seed * 100 + n
    for j in range(max(1, n // 20)):  # 엔터티 표에만 있는 id
        rows.append({"eid": f"E{extra_start + j:05d}", "x3_level": rng.choice(list(X3_LEVELS))})
    rng.shuffle(rows)
    return rows


def _record(eid: str, attr: str, value: Any, unit: str, at: str = LATEST) -> dict[str, Any]:
    return {"entity_id": eid, "attr": attr, "value": value, "unit": unit, "observed_at": at}


def _records(ents: list[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in ents:
        eid, x2_milli = e["id"], round(e["x2"] * 1000, 3)
        roll = rng.random()
        if roll >= 0.03:  # 3%는 x2 기록이 없다 → 공통 스키마 결측
            out.append(_record(eid, "A2", x2_milli, "milli"))
            if roll < 0.13:  # 이전 시각의 다른 값 → 최신 시각 규칙
                out.append(_record(eid, "A2", round(x2_milli + 3000, 3), "milli", OLDER))
            elif roll < 0.16:  # 같은 시각, 허용 오차 안 → 허용 오차 규칙
                out.append(_record(eid, "A2", round(x2_milli + 20, 3), "milli"))
            elif roll < 0.17:  # 같은 시각, 허용 오차 밖 → 해소 불가
                out.append(_record(eid, "A2", round(x2_milli + 5000, 3), "milli"))
        if rng.random() < 0.3:  # 기간 표와 겹치는 x1, 다른 단위
            x1 = e["x1"] + (2.0 if rng.random() < 0.05 else 0.0)  # 5%는 값이 어긋남
            out.append(_record(eid, "A1", round((x1 + 10.0) * 10.0, 6), "dx"))
        bad = rng.random()
        if bad < 0.01:
            out.append(_record(eid, "A9", 1.0, ""))  # 미등록 속성 코드
        elif bad < 0.015:
            out.append(_record(eid, "A2", "?", "milli"))  # 값 변환 불가
        elif bad < 0.02:
            out.append(_record(eid, "A2", x2_milli, "kelvin"))  # 미등록 단위
    rng.shuffle(out)
    return out


def generate_sources(silo_id: str) -> dict[str, list[dict[str, Any]]]:
    """사일로 원천 4파일의 내용 (기간 표 2 · 엔터티 표 · JSON 기록)."""
    seed = seed_of(silo_id)
    rng = random.Random(seed)
    ents = _entities(seed, rng)
    period_a, period_b = _period_rows(ents, rng)
    return {
        "period_a": period_a,
        "period_b": period_b,
        "entity": _entity_rows(ents, seed, rng),
        "records": _records(ents, rng),
    }


def write_sources(silo_id: str, data_dir: str | Path) -> dict[str, Path]:
    """원천을 `data_dir` 에 파일로 쓴다 (덮어쓴다). 반환: 원천 이름 → 경로."""
    base = Path(data_dir)
    base.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, rows in generate_sources(silo_id).items():
        path = base / SOURCE_FILES[name]
        if path.suffix == ".json":
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        paths[name] = path
    return paths


def ensure_sources(silo_id: str, data_dir: str | Path) -> dict[str, Path]:
    """원천 파일이 모두 있으면 그대로 두고, 하나라도 없으면 새로 쓴다."""
    base = Path(data_dir)
    paths = {name: base / fname for name, fname in SOURCE_FILES.items()}
    if all(p.is_file() for p in paths.values()):
        return paths
    return write_sources(silo_id, base)
