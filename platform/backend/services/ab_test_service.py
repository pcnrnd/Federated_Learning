"""A·B 테스트 서비스 — control(현 primary) vs treatment(섀도우) 메트릭 비교 + 승자 promote

알고리즘: Welch 두-표본 t-검정 (서로 다른 분산 가정).
원시 데이터 없음 — `metric_store`에 모인 정확도/지연/처리량 집계만 사용한다.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from fastapi import HTTPException

from config.maintenance_manager import load_ab_tests, save_ab_tests
from models.maintenance_schemas import (
    ABTest,
    ABTestEvaluation,
    ABTestRequest,
    ABWinner,
    ShadowDeploymentRequest,
)
from services import metric_store, shadow_deployment_service

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save(entry: ABTest) -> None:
    tests = load_ab_tests()
    tests[entry.test_id] = entry.model_dump()
    save_ab_tests(tests)


def list_tests(status: str | None = None) -> list[ABTest]:
    raw = load_ab_tests()
    tests = [ABTest(**v) for v in raw.values()]
    if status:
        tests = [t for t in tests if t.status == status]
    tests.sort(key=lambda t: t.created_at, reverse=True)
    return tests


def get_test(test_id: str) -> ABTest:
    raw = load_ab_tests()
    if test_id not in raw:
        raise HTTPException(status_code=404, detail="A·B 테스트를 찾을 수 없습니다")
    return ABTest(**raw[test_id])


def create_test(request: ABTestRequest) -> ABTest:
    tests = load_ab_tests()
    if request.test_id in tests:
        raise HTTPException(status_code=409, detail=f"테스트 '{request.test_id}' 중복")

    shadow = shadow_deployment_service.create_shadow(
        ShadowDeploymentRequest(
            primary_deployment_id=request.primary_deployment_id,
            shadow_version=request.treatment_version,
            target_node_ids=request.target_node_ids,
            traffic_mirror_pct=50.0,
        )
    )
    test = ABTest(
        test_id=request.test_id,
        model_name=request.model_name,
        control_version=request.control_version,
        treatment_version=request.treatment_version,
        control_deployment_id=shadow.primary_deployment_id,
        treatment_deployment_id=shadow.shadow_deployment_id,
        shadow_id=shadow.shadow_id,
        metric=request.metric,
        min_samples_per_arm=request.min_samples_per_arm,
        higher_is_better=request.higher_is_better,
        significance_threshold=request.significance_threshold,
        status="running",
        created_at=_now_iso(),
    )
    _save(test)
    logger.info(
        "A·B 테스트 시작: %s (%s vs %s, metric=%s)",
        request.test_id,
        request.control_version,
        request.treatment_version,
        request.metric,
    )
    return test


def _welch_t_stat(
    a_values: list[float], b_values: list[float]
) -> tuple[float, float, float]:
    """Welch t-statistic + 평균 두 개 반환. n<2면 0 반환."""
    na, nb = len(a_values), len(b_values)
    if na < 2 or nb < 2:
        return 0.0, sum(a_values) / na if na else 0.0, sum(b_values) / nb if nb else 0.0
    mean_a = sum(a_values) / na
    mean_b = sum(b_values) / nb
    var_a = sum((x - mean_a) ** 2 for x in a_values) / (na - 1)
    var_b = sum((x - mean_b) ** 2 for x in b_values) / (nb - 1)
    denom = math.sqrt(var_a / na + var_b / nb)
    if denom == 0.0:
        return 0.0, mean_a, mean_b
    t = (mean_a - mean_b) / denom
    return t, mean_a, mean_b


def evaluate_test(test_id: str) -> ABTestEvaluation:
    """현재 누적된 메트릭으로 통계 비교, 결과를 ABTest에 기록"""
    test = get_test(test_id)
    if test.status != "running":
        raise HTTPException(
            status_code=409,
            detail=f"running 상태에서만 evaluate 가능합니다 (현재: {test.status})",
        )

    control, _ = metric_store.query(
        model_name=test.model_name,
        version=test.control_version,
        metric=test.metric,
    )
    treatment, _ = metric_store.query(
        model_name=test.model_name,
        version=test.treatment_version,
        metric=test.metric,
    )
    a = [s.value for s in control]
    b = [s.value for s in treatment]

    t_stat, mean_a, mean_b = _welch_t_stat(a, b)
    significant = abs(t_stat) >= test.significance_threshold

    winner: ABWinner
    message: str
    if len(a) < test.min_samples_per_arm or len(b) < test.min_samples_per_arm:
        winner = "inconclusive"
        message = (
            f"표본 부족: control={len(a)}/{test.min_samples_per_arm}, "
            f"treatment={len(b)}/{test.min_samples_per_arm}"
        )
    elif not significant:
        winner = "inconclusive"
        message = (
            f"유의하지 않음 (|t|={abs(t_stat):.2f} < {test.significance_threshold})"
        )
    else:
        # higher_is_better 에 따라 승자 결정
        if test.higher_is_better:
            winner = "control" if mean_a > mean_b else "treatment"
        else:
            winner = "control" if mean_a < mean_b else "treatment"
        message = (
            f"유의 (|t|={abs(t_stat):.2f} ≥ {test.significance_threshold}) — "
            f"승자 {winner} (control={mean_a:.4f}, treatment={mean_b:.4f})"
        )

    updated = test.model_copy(
        update={
            "status": "evaluated",
            "winner": winner,
            "t_stat": t_stat,
            "control_mean": mean_a,
            "treatment_mean": mean_b,
            "control_samples": len(a),
            "treatment_samples": len(b),
            "evaluated_at": _now_iso(),
        }
    )
    _save(updated)
    logger.info("A·B 평가: %s — %s (%s)", test_id, winner, message)
    return ABTestEvaluation(
        test_id=test_id,
        metric=test.metric,
        control_mean=mean_a,
        treatment_mean=mean_b,
        control_samples=len(a),
        treatment_samples=len(b),
        t_stat=t_stat,
        winner=winner,
        significant=significant,
        message=message,
    )


def promote_winner(test_id: str) -> ABTest:
    """평가 후 승자에 따라 promote/abort 자동 처리"""
    test = get_test(test_id)
    if test.status != "evaluated":
        raise HTTPException(
            status_code=409,
            detail=f"evaluated 상태에서만 promote 가능합니다 (현재: {test.status})",
        )
    if test.winner == "treatment":
        shadow_deployment_service.promote_shadow(test.shadow_id)
        status = "promoted"
    else:
        # control 승리 또는 inconclusive — 섀도우 폐기
        shadow_deployment_service.abort_shadow(test.shadow_id)
        status = "aborted"

    finalized = test.model_copy(update={"status": status, "promoted_at": _now_iso()})
    _save(finalized)
    logger.info("A·B 종료: %s → %s", test_id, status)
    return finalized


def abort_test(test_id: str) -> ABTest:
    """평가 전/중 강제 중단"""
    test = get_test(test_id)
    if test.status in ("promoted", "aborted"):
        raise HTTPException(status_code=409, detail=f"이미 종료된 테스트 ({test.status})")
    shadow_deployment_service.abort_shadow(test.shadow_id)
    aborted = test.model_copy(
        update={"status": "aborted", "promoted_at": _now_iso()}
    )
    _save(aborted)
    return aborted
