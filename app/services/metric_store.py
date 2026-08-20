"""메트릭 시계열 저장소 (rolling window + 선택적 SQLite 영속)

성능 우선 인메모리가 기본이며, FED_STORAGE=sqlite 일 때 ingest/query 시 SQLite에도 기록한다.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from typing import Iterable

from models.monitoring_schemas import MetricIngest, MetricSample
from storage.settings import get_backend, get_sqlite_path

logger = logging.getLogger(__name__)

_MAX_PER_KEY = 1000  # node × model × version × metric 당 최근 N개
_lock = threading.Lock()
_store: dict[tuple[str, str, str, str], deque[MetricSample]] = defaultdict(
    lambda: deque(maxlen=_MAX_PER_KEY)
)


def _key(node_id: str, model_name: str, version: str, metric: str) -> tuple[str, str, str, str]:
    return (node_id, model_name, version, metric)


def _persist_sqlite(sample: MetricSample) -> None:
    """SQLite metrics 테이블에 샘플 1건을 기록한다."""
    if get_backend() != "sqlite":
        return
    try:
        from storage.sqlite_store import connect

        with connect(get_sqlite_path()) as conn:
            conn.execute(
                """
                INSERT INTO metrics (node_id, model_name, version, metric, value, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sample.node_id,
                    sample.model_name,
                    sample.version,
                    sample.metric,
                    sample.value,
                    sample.timestamp,
                ),
            )
    except Exception as exc:  # noqa: BLE001 — 영속 실패는 ingest를 막지 않음
        logger.warning("메트릭 SQLite 영속 실패: %s", exc)


def _query_sqlite(
    *,
    model_name: str | None = None,
    version: str | None = None,
    node_id: str | None = None,
    metric: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> list[MetricSample]:
    """SQLite에서 필터링된 메트릭을 조회한다."""
    if get_backend() != "sqlite":
        return []
    try:
        from storage.sqlite_store import connect

        clauses: list[str] = []
        params: list[object] = []
        if node_id:
            clauses.append("node_id = ?")
            params.append(node_id)
        if model_name:
            clauses.append("model_name = ?")
            params.append(model_name)
        if version:
            clauses.append("version = ?")
            params.append(version)
        if metric:
            clauses.append("metric = ?")
            params.append(metric)
        if start_time:
            clauses.append("timestamp >= ?")
            params.append(start_time)
        if end_time:
            clauses.append("timestamp <= ?")
            params.append(end_time)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT node_id, model_name, version, metric, value, timestamp
            FROM metrics {where}
            ORDER BY timestamp ASC
        """
        with connect(get_sqlite_path()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            MetricSample(
                node_id=r["node_id"],
                model_name=r["model_name"],
                version=r["version"],
                metric=r["metric"],
                value=r["value"],
                timestamp=r["timestamp"],
            )
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("메트릭 SQLite 조회 실패: %s", exc)
        return []


def ingest(sample: MetricIngest) -> None:
    """단일 메트릭 샘플을 적재한다."""
    record = MetricSample(
        node_id=sample.node_id,
        model_name=sample.model_name,
        version=sample.version,
        metric=sample.metric,
        value=sample.value,
        timestamp=sample.timestamp,
    )
    with _lock:
        key = _key(sample.node_id, sample.model_name, sample.version, sample.metric)
        _store[key].append(record)
    _persist_sqlite(record)


def query(
    *,
    model_name: str | None = None,
    version: str | None = None,
    node_id: str | None = None,
    metric: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> tuple[list[MetricSample], int]:
    """필터링된 메트릭 샘플과 전체 건수를 반환 (시간 오름차순)."""
    sqlite_rows = _query_sqlite(
        model_name=model_name,
        version=version,
        node_id=node_id,
        metric=metric,
        start_time=start_time,
        end_time=end_time,
    )
    if sqlite_rows:
        all_samples = sqlite_rows
    else:
        with _lock:
            all_samples = []
            for key, samples in _store.items():
                k_node, k_model, k_version, k_metric = key
                if node_id and k_node != node_id:
                    continue
                if model_name and k_model != model_name:
                    continue
                if version and k_version != version:
                    continue
                if metric and k_metric != metric:
                    continue
                all_samples.extend(samples)
        all_samples.sort(key=lambda s: s.timestamp)
        if start_time:
            all_samples = [s for s in all_samples if s.timestamp >= start_time]
        if end_time:
            all_samples = [s for s in all_samples if s.timestamp <= end_time]

    total = len(all_samples)
    if offset:
        all_samples = all_samples[offset:]
    if limit is not None:
        all_samples = all_samples[:limit]
    return all_samples, total


def latest(
    *,
    model_name: str,
    version: str,
    metric: str,
) -> MetricSample | None:
    """가장 최근 샘플 단건 (노드 무관 — 글로벌 최신)"""
    candidates, _ = query(model_name=model_name, version=version, metric=metric)
    return candidates[-1] if candidates else None


def aggregate(
    *,
    model_name: str,
    version: str,
    metric: str,
    samples: Iterable[MetricSample] | None = None,
) -> dict[str, float]:
    """현재 보유 샘플의 평균/최소/최대/카운트 집계"""
    if samples is not None:
        data = list(samples)
    else:
        data, _ = query(model_name=model_name, version=version, metric=metric)
    if not data:
        return {"count": 0, "mean": 0.0, "min": 0.0, "max": 0.0}
    values = [s.value for s in data]
    return {
        "count": float(len(values)),
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
    }


def clear() -> None:
    """테스트용 전역 상태 초기화"""
    with _lock:
        _store.clear()
