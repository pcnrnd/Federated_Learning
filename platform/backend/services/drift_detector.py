"""데이터 드리프트 감지 — Population Stability Index(PSI)

개인정보 보호:
  * 원시 데이터를 절대 다루지 않는다.
  * 사일로가 사전 계산한 히스토그램(bin 카운트)만 비교한다.

PSI 해석 (업계 표준):
  * PSI <  0.10 → stable
  * 0.10 ≤ PSI < 0.25 → warning
  * PSI ≥ 0.25 → critical
"""
from __future__ import annotations

import logging
import math
from typing import Sequence

from fastapi import HTTPException

from config.monitoring_manager import load_baselines, save_baselines
from models.monitoring_schemas import (
    BaselineRequest,
    DistributionStats,
    DriftReport,
    DriftSeverity,
)

logger = logging.getLogger(__name__)

PSI_WARNING_THRESHOLD = 0.10
PSI_CRITICAL_THRESHOLD = 0.25
_EPSILON = 1e-6  # log(0) 방지


def _baseline_key(model_name: str, version: str, feature: str) -> str:
    return f"{model_name}::{version}::{feature}"


def set_baseline(request: BaselineRequest) -> None:
    """모델/특성별 베이스라인 분포 등록"""
    if len(request.bin_counts) != len(request.bin_edges) - 1:
        raise HTTPException(
            status_code=400,
            detail="bin_counts 길이는 bin_edges 길이 - 1 이어야 합니다",
        )
    baselines = load_baselines()
    baselines[_baseline_key(request.model_name, request.version, request.feature)] = {
        "bin_edges": list(request.bin_edges),
        "bin_counts": list(request.bin_counts),
    }
    save_baselines(baselines)
    logger.info(
        "베이스라인 등록: model=%s@%s feature=%s",
        request.model_name,
        request.version,
        request.feature,
    )


def get_baseline(model_name: str, version: str, feature: str) -> dict[str, list]:
    baselines = load_baselines()
    key = _baseline_key(model_name, version, feature)
    if key not in baselines:
        raise HTTPException(status_code=404, detail=f"베이스라인 없음: {key}")
    return baselines[key]


def _normalize(counts: Sequence[int]) -> list[float]:
    total = sum(counts)
    if total <= 0:
        return [0.0 for _ in counts]
    return [c / total for c in counts]


def compute_psi(expected_counts: Sequence[int], actual_counts: Sequence[int]) -> float:
    """PSI 계산. 두 분포의 빈 수가 일치해야 한다."""
    if len(expected_counts) != len(actual_counts):
        raise ValueError("expected/actual 빈 길이가 다릅니다")
    expected = _normalize(expected_counts)
    actual = _normalize(actual_counts)

    psi = 0.0
    for e, a in zip(expected, actual):
        e_safe = max(e, _EPSILON)
        a_safe = max(a, _EPSILON)
        psi += (a_safe - e_safe) * math.log(a_safe / e_safe)
    return psi


def classify(psi: float) -> DriftSeverity:
    if psi < PSI_WARNING_THRESHOLD:
        return "stable"
    if psi < PSI_CRITICAL_THRESHOLD:
        return "warning"
    return "critical"


def detect_drift(stats: DistributionStats) -> DriftReport:
    """베이스라인과 현재 분포 비교해 PSI/심각도 계산"""
    baseline = get_baseline(stats.model_name, stats.version, stats.feature)
    baseline_counts = baseline["bin_counts"]
    if len(baseline_counts) != len(stats.bin_counts):
        raise HTTPException(
            status_code=400,
            detail=(
                f"베이스라인 빈 수({len(baseline_counts)})와 "
                f"현재 빈 수({len(stats.bin_counts)})가 일치하지 않습니다"
            ),
        )

    psi = compute_psi(baseline_counts, stats.bin_counts)
    severity = classify(psi)
    return DriftReport(
        model_name=stats.model_name,
        version=stats.version,
        feature=stats.feature,
        psi=psi,
        severity=severity,
        baseline_total=sum(baseline_counts),
        current_total=sum(stats.bin_counts),
    )
