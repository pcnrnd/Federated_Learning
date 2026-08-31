"""알림 서비스 — 임계값 검사 + 자동 롤백/재교육 트리거

알림 발화 흐름:
  1. 메트릭/드리프트 발생 → evaluate_*  호출
  2. 매칭되는 AlertRule이 있고 임계값 위반 → Alert 생성
  3. rule.auto_rollback=true 면 deployment_service.rollback_deployment 호출
  4. drift critical → RetrainTrigger 생성 (외부 워크플로우가 폴링/소비)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from config.monitoring_manager import (
    load_alert_rules,
    load_alerts,
    save_alert_rules,
    save_alerts,
)
from models.monitoring_schemas import (
    Alert,
    AlertRule,
    DriftReport,
    MetricSample,
    RetrainTrigger,
)
from services import audit_logger

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_rule(rule: AlertRule) -> AlertRule:
    rules = load_alert_rules()
    rules[rule.rule_id] = rule.model_dump()
    save_alert_rules(rules)
    audit_logger.record("rule_upsert", rule_id=rule.rule_id, model=rule.model_name)
    return rule


def list_rules() -> list[AlertRule]:
    return [AlertRule(**v) for v in load_alert_rules().values()]


def delete_rule(rule_id: str) -> None:
    rules = load_alert_rules()
    if rule_id not in rules:
        raise HTTPException(status_code=404, detail="규칙 없음")
    del rules[rule_id]
    save_alert_rules(rules)
    audit_logger.record("rule_delete", rule_id=rule_id)


def list_alerts(
    status: str | None = None,
    model_name: str | None = None,
    metric: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> tuple[list[Alert], int]:
    """알림 목록을 필터·페이지네이션하여 반환한다."""
    raw = load_alerts()
    alerts = [Alert(**v) for v in raw.values()]
    if status:
        alerts = [a for a in alerts if a.status == status]
    if model_name:
        alerts = [a for a in alerts if a.model_name == model_name]
    if metric:
        alerts = [a for a in alerts if a.metric == metric]
    if start_time:
        alerts = [a for a in alerts if a.triggered_at >= start_time]
    if end_time:
        alerts = [a for a in alerts if a.triggered_at <= end_time]
    alerts.sort(key=lambda a: a.triggered_at, reverse=True)
    total = len(alerts)
    if offset:
        alerts = alerts[offset:]
    if limit is not None:
        alerts = alerts[:limit]
    return alerts, total


def _save_alert(alert: Alert) -> None:
    alerts = load_alerts()
    alerts[alert.alert_id] = alert.model_dump()
    save_alerts(alerts)


def ack_alert(alert_id: str) -> Alert:
    alerts = load_alerts()
    if alert_id not in alerts:
        raise HTTPException(status_code=404, detail="알림 없음")
    alert = Alert(**alerts[alert_id]).model_copy(update={"status": "acked"})
    _save_alert(alert)
    audit_logger.record("alert_ack", alert_id=alert_id)
    return alert


def _violates(rule: AlertRule, value: float) -> bool:
    if rule.comparison == "lt":
        return value < rule.threshold
    return value > rule.threshold


def _maybe_rollback(rule: AlertRule, version: str) -> str | None:
    """rule.auto_rollback=true 면 해당 모델/버전의 최근 배포를 롤백한다."""
    if not rule.auto_rollback:
        return None
    # 지연 임포트로 순환 의존성 회피
    from services import deployment_service

    candidates = [
        d
        for d in deployment_service.list_deployments()
        if d.model_name == rule.model_name
        and d.version == version
        and d.status == "running"
        and d.previous_deployment_id is not None
    ]
    if not candidates:
        logger.info("자동 롤백 대상 배포 없음: %s@%s", rule.model_name, version)
        return None
    candidates.sort(key=lambda d: d.created_at, reverse=True)
    target = candidates[0]
    try:
        new_entry = deployment_service.rollback_deployment(target.deployment_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("자동 롤백 실패: %s", exc)
        audit_logger.record(
            "rollback_failed",
            rule_id=rule.rule_id,
            model=rule.model_name,
            version=version,
            error=str(exc),
        )
        return None
    audit_logger.record(
        "rollback_triggered",
        rule_id=rule.rule_id,
        from_deployment=target.deployment_id,
        to_deployment=new_entry.deployment_id,
    )
    return new_entry.deployment_id


def _emit_alert(
    rule: AlertRule,
    version: str,
    observed: float,
    message: str,
    rollback_deployment_id: str | None,
) -> Alert:
    alert = Alert(
        alert_id=uuid.uuid4().hex,
        rule_id=rule.rule_id,
        model_name=rule.model_name,
        version=version,
        metric=rule.metric,
        observed_value=observed,
        threshold=rule.threshold,
        status="open",
        triggered_at=_now_iso(),
        message=message,
        triggered_rollback_deployment_id=rollback_deployment_id,
    )
    _save_alert(alert)
    audit_logger.record(
        "alert_open",
        alert_id=alert.alert_id,
        rule_id=rule.rule_id,
        observed=observed,
        threshold=rule.threshold,
    )
    return alert


def evaluate_metric(sample: MetricSample) -> list[Alert]:
    """메트릭 샘플에 대해 적용 가능한 모든 규칙을 평가"""
    triggered: list[Alert] = []
    for rule in list_rules():
        if rule.model_name != sample.model_name:
            continue
        if rule.metric != sample.metric:
            continue
        if not _violates(rule, sample.value):
            continue
        rollback_id = _maybe_rollback(rule, sample.version)
        msg = (
            f"{sample.metric}={sample.value:.4f} {rule.comparison} {rule.threshold} "
            f"위반 (model={sample.model_name}@{sample.version})"
        )
        triggered.append(_emit_alert(rule, sample.version, sample.value, msg, rollback_id))
    return triggered


def evaluate_drift(report: DriftReport) -> tuple[list[Alert], RetrainTrigger | None]:
    """드리프트 리포트에 대해 metric='drift' 규칙을 평가하고
    critical 일 경우 RetrainTrigger를 함께 발행한다.
    """
    triggered: list[Alert] = []
    for rule in list_rules():
        if rule.model_name != report.model_name or rule.metric != "drift":
            continue
        if not _violates(rule, report.psi):
            continue
        rollback_id = _maybe_rollback(rule, report.version)
        msg = (
            f"drift PSI={report.psi:.4f} {rule.comparison} {rule.threshold} "
            f"위반 (severity={report.severity}, feature={report.feature})"
        )
        triggered.append(_emit_alert(rule, report.version, report.psi, msg, rollback_id))

    retrain: RetrainTrigger | None = None
    if report.severity == "critical":
        retrain = RetrainTrigger(
            model_name=report.model_name,
            version=report.version,
            reason=f"PSI critical (={report.psi:.4f}) on feature '{report.feature}'",
            triggered_at=_now_iso(),
        )
        audit_logger.record(
            "retrain_trigger",
            model=report.model_name,
            version=report.version,
            psi=report.psi,
            feature=report.feature,
        )
    return triggered, retrain


def latest_retrain_triggers(model_name: str | None = None) -> list[dict[str, Any]]:
    """감사 로그에서 retrain_trigger 이벤트만 추출"""
    events = audit_logger.tail(1000)
    out = [e for e in events if e.get("event") == "retrain_trigger"]
    if model_name:
        out = [e for e in out if e.get("model") == model_name]
    return out
