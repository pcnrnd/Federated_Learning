"""사일로 리소스 모니터링 서비스

기능:
  * 사일로별 자원 임계값 등록 (CPU/메모리/GPU/디스크 백분율)
  * 사일로의 리소스 샘플 수집 (인메모리 rolling window)
  * 임계값 초과 시 ResourceAlert + 감사 로그 발행
  * Batch Scheduler가 호출하는 `is_silo_available` 자원 게이트 헬퍼

샘플은 기본적으로 휘발성(인메모리)이다. FED_STORAGE=sqlite 이면 SQLite `resource_samples`에도
수집 순서대로 기록하고, 프로세스가 처음 보는 사일로는 그 기록으로 메모리 창을 채워 재시작 후에도
남는다(사일로당 최근 500개). 최신 관측의 기준은 메모리 창이다 — 기록에 실패한 샘플이 있어도
과거 DB 행이 더 새 관측을 가리지 않는다.
장기 보관은 Prometheus 등 외부 도구에 위임한다.
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
from storage.settings import get_backend, get_sqlite_path

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


_SAMPLE_COLUMNS = "silo_id, cpu_pct, mem_pct, gpu_pct, disk_pct, timestamp"


def _persist_sqlite(sample: ResourceSample) -> None:
    """SQLite resource_samples에 1건 기록하고 그 사일로는 최근 _MAX_SAMPLES_PER_SILO개만 남긴다."""
    if get_backend() != "sqlite":
        return
    try:
        from storage.sqlite_store import connect

        with connect(get_sqlite_path()) as conn:
            conn.execute(
                f"INSERT INTO resource_samples ({_SAMPLE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    sample.silo_id,
                    sample.cpu_pct,
                    sample.mem_pct,
                    sample.gpu_pct,
                    sample.disk_pct,
                    sample.timestamp,
                ),
            )
            conn.execute(
                """
                DELETE FROM resource_samples
                WHERE silo_id = ? AND id NOT IN (
                    SELECT id FROM resource_samples WHERE silo_id = ? ORDER BY id DESC LIMIT ?
                )
                """,
                (sample.silo_id, sample.silo_id, _MAX_SAMPLES_PER_SILO),
            )
    except Exception as exc:  # noqa: BLE001 — 영속 실패는 수집을 막지 않음
        logger.warning("리소스 샘플 SQLite 영속 실패: %s", exc)


def _query_sqlite(where: str, params: tuple[object, ...]) -> list[ResourceSample]:
    """SQLite에서 샘플을 삽입 순서로 읽는다. sqlite 모드가 아니거나 실패하면 빈 목록.

    where는 이 모듈의 고정 문자열만 받는다 — 값은 params로 바인딩.
    """
    if get_backend() != "sqlite":
        return []
    try:
        from storage.sqlite_store import connect

        sql = f"SELECT {_SAMPLE_COLUMNS} FROM resource_samples WHERE {where} ORDER BY id ASC"
        with connect(get_sqlite_path()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [ResourceSample(**dict(r)) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("리소스 샘플 SQLite 조회 실패: %s", exc)
        return []


def _bucket_locked(silo_id: str) -> deque[ResourceSample] | None:
    """사일로의 메모리 창. 이 프로세스가 처음 보는 사일로면 SQLite 기록(재시작 전 샘플)으로 채운다.

    _lock을 잡은 채 호출한다.
    """
    bucket = _samples.get(silo_id)
    if bucket is None:
        persisted = _query_sqlite("silo_id = ?", (silo_id,))
        if persisted:
            bucket = _samples[silo_id] = deque(persisted, maxlen=_MAX_SAMPLES_PER_SILO)
    return bucket


def ingest_sample(sample: ResourceSample) -> dict[str, list[str]]:
    """리소스 샘플을 저장하고 임계값 평가 → 발화된 알림 id 반환"""
    with _lock:
        _bucket_locked(sample.silo_id)
        _samples[sample.silo_id].append(sample)
        triggered = _check_against_limit(sample.silo_id, sample)
        # ponytail: SQLite 기록도 잠금 안에서 해 DB 순서를 수집 순서와 맞춘다(수집이 직렬화된다).
        # 수집량이 병목이 되면 사일로별 잠금으로 나눈다.
        _persist_sqlite(sample)
    return {"alerts": [a.alert_id for a in triggered]}


def latest_sample(silo_id: str) -> ResourceSample | None:
    with _lock:
        bucket = _bucket_locked(silo_id)
        return bucket[-1] if bucket else None


def list_samples(
    silo_id: str,
    limit: int = 100,
    start_time: str | None = None,
    end_time: str | None = None,
    offset: int = 0,
) -> tuple[list[ResourceSample], int]:
    """사일로 리소스 샘플을 시간 범위·페이지네이션으로 조회한다."""
    with _lock:
        bucket = _bucket_locked(silo_id)
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
    # 이 프로세스가 본 사일로 + 재시작 전 SQLite에만 남은 사일로
    persisted = _query_sqlite(
        "id IN (SELECT MAX(id) FROM resource_samples GROUP BY silo_id)", ()
    )
    with _lock:
        active_silos = set(_samples) | {s.silo_id for s in persisted}
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
