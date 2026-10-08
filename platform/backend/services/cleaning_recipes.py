"""정제 step 카탈로그 — 사일로 SDK와 공유되는 step 스키마 정의.

각 step의 의미와 필수 파라미터는 SDK가 해석하여 로컬 데이터에 적용한다.
중앙은 step 메타만 저장한다.
"""
from __future__ import annotations

from typing import Any

# (step_type, required_params, description)
STEP_CATALOG: dict[str, dict[str, Any]] = {
    "drop_nulls": {
        "required": ["columns"],
        "description": "지정 컬럼이 null인 행 제거",
    },
    "clip_outliers": {
        "required": ["column", "lower", "upper"],
        "description": "지정 컬럼 값을 [lower, upper] 범위로 클리핑",
    },
    "dedupe": {
        "required": ["keys"],
        "description": "지정 키 조합 기준 중복 제거",
    },
    "cast": {
        "required": ["column", "to"],
        "description": "컬럼 타입 변환 (int/float/str/bool)",
    },
    "normalize": {
        "required": ["column"],
        "description": "z-score 정규화 또는 min-max (params.method)",
    },
    "trim_whitespace": {
        "required": ["columns"],
        "description": "문자열 컬럼의 양끝 공백 제거",
    },
    "lowercase": {
        "required": ["columns"],
        "description": "문자열 컬럼 소문자화",
    },
    "regex_filter": {
        "required": ["column", "pattern"],
        "description": "정규식 매칭되지 않는 행 제거",
    },
    # ---------- 다원천 단계 — 레시피 매핑표(mapping)가 필요하다 ----------
    "map_schema": {
        "required": ["sources"],
        "needs_mapping": True,
        "description": "표 원천을 매핑표대로 공통 스키마에 맞춤 (컬럼명·형식·단위·코드)",
    },
    "validate_schema": {
        "required": [],
        "needs_mapping": True,
        "description": "공통 스키마(존재·형식·유한·범위) 위반 행 제외, 사유별 집계",
    },
    "union_sources": {
        "required": ["sources", "into"],
        "needs_mapping": True,
        "description": "수평 결합 — 공통 스키마 원천들의 행 결합, 원천 간·안 중복 제거",
    },
    "join_sources": {
        "required": ["left", "right", "into"],
        "needs_mapping": True,
        "description": "수직 결합 — 키 inner join, 제외 수(한쪽에만 있는 키·키 결측) 기록",
    },
}

# 매핑표의 원천 이름을 가리키는 파라미터 (단계 → 파라미터 이름)
_SOURCE_PARAMS: dict[str, str] = {"map_schema": "sources"}


def validate_step_params(step_type: str, params: dict[str, Any]) -> None:
    """레시피 등록 시 호출 — 누락된 필수 파라미터를 사전에 거부"""
    if step_type not in STEP_CATALOG:
        raise ValueError(f"지원하지 않는 step: {step_type}")
    missing = [k for k in STEP_CATALOG[step_type]["required"] if k not in params]
    if missing:
        raise ValueError(f"'{step_type}' 누락 필수 파라미터: {missing}")


def validate_mapping_usage(
    step_type: str, params: dict[str, Any], mapping_sources: set[str] | None
) -> None:
    """다원천 단계가 매핑표를 갖췄는지, 가리키는 원천이 매핑표에 있는지 검사.

    mapping_sources: 매핑표의 원천 이름 집합 (매핑표가 없으면 None)
    """
    if not STEP_CATALOG[step_type].get("needs_mapping"):
        return
    if mapping_sources is None:
        raise ValueError(f"'{step_type}' 단계에는 레시피 매핑표(mapping)가 필요합니다")
    param = _SOURCE_PARAMS.get(step_type)
    if param is None:
        return
    value = params[param]
    names = value if isinstance(value, list) else [value]
    unknown = [n for n in names if n not in mapping_sources]
    if unknown:
        raise ValueError(f"'{step_type}': 매핑표에 없는 원천 {unknown}")
