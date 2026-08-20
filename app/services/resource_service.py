"""사일로 리소스 모니터링 서비스

기능:
  * 사일로별 자원 임계값 등록 (CPU/메모리/GPU/디스크 백분율)
  * 사일로의 리소스 샘플 수집 (인메모리 rolling window)
  * 임계값 초과 시 ResourceAlert + 감사 로그 발행
  * Batch Scheduler가 호출하는 `is_silo_available` 자원 게이트 헬퍼

샘플은 휘발성이며 (프로세스 재시작 시 사라짐), Prometheus 등 영구 저장은 외부 도구에 위임한다.
"""
from __future__ import annotations

import logging
import threading
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import HTTPException

from config.resource_manager import load_resource_limits, save_resource_limits
from models.resource_schemas import (
    ResourceAlert,
    ResourceLimit,
    ResourceSample,
    ResourceUsageSummary,
)
from services import audit_logger

logger = logging.getLogger(__name__)

_MAX_SAMPLES_PER_SILO = 500
_lock = threading.Lock()
_samples: dict[str, deque[ResourceSample]] = defaultdict(
    lambda: deque(maxlen=_MAX_SAMPLES_PER_SILO)
)
_alerts: dict[str, ResourceAlert] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- 임계값 ----------

def set_limit(limit: ResourceLimit) -> ResourceLimit:
    limits = load_resource_limits()
    limits[limit.silo_id] = limit.model_dump()
    save_resource_limits(limits)
    logger.info(
        "임계값 등록: %s (cpu=%s, mem=%s, gpu=%s, disk=%s)",
        limit.silo_id,
        limit.cpu_pct_max,
        limit.mem_pct_max,
        limit.gpu_pct_max,
        limit.disk_pct_max,
    )
    return limit


def get_limit(silo_id: str) -> ResourceLimit | None:
    limits = load_resource_limits()
    if silo_id not in limits:
        return None
    return ResourceLimit(**limits[silo_id])


def list_limits() -> list[ResourceLimit]:
    return [ResourceLimit(**v) for v in load_resource_limits().values()]


def delete_limit(silo_id: str) -> None:
    limits = load_resource_limits()
    if silo_id not in limits:
        raise HTTPException(status_code=404, detail=f"임계값 없음: {silo_id}")
    del limits[silo_id]
    save_resource_limits(limits)


# ---------- 샘플 수집 ----------

def _check_against_limit(
    silo_id: str,
    sample: ResourceSample,
) -> list[ResourceAlert]:
    limit = get_limit(silo_id)
    if limit is None:
        return []
    triggered: list[ResourceAlert] = []
    checks = [
        ("cpu", sample.cpu_pct, limit.cpu_pct_max),
        ("mem", sample.mem_pct, limit.mem_pct_max),
        ("gpu", sample.gpu_pct, limit.gpu_pct_max),
        ("disk", sample.disk_pct, limit.disk_pct_max),
    ]
    for metric, observed, cap in checks:
        if cap is None or observed is None:
            continue
        if observed > cap:
            alert = ResourceAlert(
                alert_id=uuid.uuid4().hex,
                silo_id=silo_id,
                metric=metric,
                observed=observed,
                limit=cap,
                triggered_at=_now_iso(),
                message=f"{silo_id} {metric}={observed:.1f}% > {cap:.1f}%",
            )
            _alerts[alert.alert_id] = alert
            audit_logger.record(
                "resource_alert",
                silo_id=silo_id,
                metric=metric,
                observed=observed,
                limit=cap,
            )
            triggered.append(alert)
    return triggered


def ingest_sample(sample: ResourceSample) -> dict[str, list[str]]:
    """리소스 샘플을 저장하고 임계값 평가 → 발화된 알림 id 반환"""
    with _lock:
        _samples[sample.silo_id].append(sample)
        triggered = _check_against_limit(sample.silo_id, sample)
    return {"alerts": [a.alert_id for a in triggered]}


def latest_sample(silo_id: str) -> ResourceSample | None:
    with _lock:
        bucket = _samples.get(silo_id)
        if not bucket:
            return None
        return bucket[-1]


def list_samples(
    silo_id: str,
    limit: int = 100,
    start_time: str | None = None,
    end_time: str | None = None,
    offset: int = 0,
) -> tuple[list[ResourceSample], int]:
    """사일로 리소스 샘플을 시간 범위·페이지네이션으로 조회한다."""
    with _lock:
        bucket = _samples.get(silo_id)
        if not bucket:
            return [], 0
        items = list(bucket)
    items.sort(key=lambda s: s.timestamp)
    if start_time:
        items = [s for s in items if s.timestamp >= start_time]
    if end_time:
        items = [s for s in items if s.timestamp <= end_time]
    total = len(items)
    if offset:
        items = items[offset:]
    items = items[:limit]
    return items, total


def list_alerts(
    silo_id: str | None = None,
    metric: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> tuple[list[ResourceAlert], int]:
    """리소스 알림을 필터·페이지네이션하여 반환한다."""
    alerts = list(_alerts.values())
    if silo_id:
        alerts = [a for a in alerts if a.silo_id == silo_id]
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


def clear_samples() -> None:
    """테스트용"""
    with _lock:
        _samples.clear()
        _alerts.clear()


# ---------- Batch Scheduling 게이트 ----------

def is_silo_available(silo_id: str) -> bool:
    """가장 최근 샘플이 임계값을 초과하지 않았는지 — Batch tick에서 호출"""
    sample = latest_sample(silo_id)
    if sample is None:
        return True  # 데이터 없음 = 차단 안 함 (관측 X)
    limit = get_limit(silo_id)
    if limit is None:
        return True
    if limit.cpu_pct_max is not None and sample.cpu_pct > limit.cpu_pct_max:
        return False
    if limit.mem_pct_max is not None and sample.mem_pct > limit.mem_pct_max:
        return False
    if (
        limit.gpu_pct_max is not None
        and sample.gpu_pct is not None
        and sample.gpu_pct > limit.gpu_pct_max
    ):
        return False
    if (
        limit.disk_pct_max is not None
        and sample.disk_pct is not None
        and sample.disk_pct > limit.disk_pct_max
    ):
        return False
    return True


def group_has_pressure(member_silo_ids: list[str]) -> bool:
    """그룹의 단 한 노드라도 자원 압박 상태면 True"""
    return any(not is_silo_available(s) for s in member_silo_ids)


def usage_summary() -> list[ResourceUsageSummary]:
    summaries: list[ResourceUsageSummary] = []
    with _lock:
        active_silos = list(_samples.keys())
    for silo_id in active_silos:
        sample = latest_sample(silo_id)
        if sample is None:
            continue
        summaries.append(
            ResourceUsageSummary(
                silo_id=silo_id,
                last_sample_at=sample.timestamp,
                cpu_pct=sample.cpu_pct,
                mem_pct=sample.mem_pct,
                gpu_pct=sample.gpu_pct,
                disk_pct=sample.disk_pct,
                over_budget=not is_silo_available(silo_id),
            )
        )
    summaries.sort(key=lambda s: s.silo_id)
    return summaries
