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
}


def validate_step_params(step_type: str, params: dict[str, Any]) -> None:
    """레시피 등록 시 호출 — 누락된 필수 파라미터를 사전에 거부"""
    if step_type not in STEP_CATALOG:
        raise ValueError(f"지원하지 않는 step: {step_type}")
    missing = [k for k in STEP_CATALOG[step_type]["required"] if k not in params]
    if missing:
        raise ValueError(f"'{step_type}' 누락 필수 파라미터: {missing}")
