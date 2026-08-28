"""SQLite 기반 DictRepository 구현."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from .sqlite_store import connect

T = TypeVar("T")


def _retry_on_locked(operation: Callable[[], T]) -> T:
    """database is locked 발생 시 짧게 재시도한다."""
    last: sqlite3.OperationalError | None = None
    for attempt in range(8):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            last = exc
            if "locked" not in str(exc).lower() or attempt >= 7:
                raise
            time.sleep(0.025 * (attempt + 1))
    if last:
        raise last
    raise RuntimeError("unreachable")


def _json_load(raw: str) -> Any:
    return json.loads(raw)


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=False)


class SqliteFlatRepository:
    """id → payload dict를 단일 테이블에 저장한다."""

    def __init__(self, db_path: Path, *, table: str, id_column: str = "id") -> None:
        self._db_path = db_path
        self._table = table
        self._id_column = id_column

    def load(self) -> dict[str, Any]:
        with connect(self._db_path) as conn:
            rows = conn.execute(
                f"SELECT {self._id_column}, payload FROM {self._table}"
            ).fetchall()
        return {row[self._id_column]: _json_load(row["payload"]) for row in rows}

    def save(self, data: dict[str, Any]) -> None:
        def _write() -> None:
            with connect(self._db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute(f"DELETE FROM {self._table}")
                    for key, payload in data.items():
                        conn.execute(
                            f"INSERT INTO {self._table} ({self._id_column}, payload) VALUES (?, ?)",
                            (str(key), _json_dump(payload)),
                        )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

        _retry_on_locked(_write)


class SqliteModelsRepository:
    """중첩 models.yaml 구조 {name: {version: payload}} 를 model_versions 테이블에 저장."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def load(self) -> dict[str, Any]:
        with connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT model_name, version, payload FROM model_versions"
            ).fetchall()
        registry: dict[str, Any] = {}
        for row in rows:
            registry.setdefault(row["model_name"], {})[row["version"]] = _json_load(
                row["payload"]
            )
        return registry

    def save(self, data: dict[str, Any]) -> None:
        def _write() -> None:
            with connect(self._db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute("DELETE FROM model_versions")
                    for name, versions in data.items():
                        if not isinstance(versions, dict):
                            continue
                        for version, payload in versions.items():
                            conn.execute(
                                "INSERT INTO model_versions (model_name, version, payload) VALUES (?, ?, ?)",
                                (str(name), str(version), _json_dump(payload)),
                            )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

        _retry_on_locked(_write)


class SqliteMetricsRepository:
    """메트릭 시계열 — load는 샘플 목록 dict가 아닌 인메모리 호환용 빈 dict, save는 append-only."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def load(self) -> dict[str, Any]:
        """SQLite metrics는 행 기반이므로 flat dict 대신 빈 dict를 반환 (마이그레이션 전용)."""
        return {}

    def save(self, data: dict[str, Any]) -> None:
        """마이그레이션/테스트용 — {key: sample_dict} 형태를 INSERT."""
        with connect(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for item in data.values():
                    if not isinstance(item, dict):
                        continue
                    conn.execute(
                        """INSERT INTO metrics
                           (node_id, model_name, version, metric, value, timestamp)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            item["node_id"],
                            item["model_name"],
                            item["version"],
                            item["metric"],
                            float(item["value"]),
                            item["timestamp"],
                        ),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def replace_all(self, samples: list[dict[str, Any]]) -> None:
        """전체 메트릭 스냅샷을 교체한다."""
        with connect(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM metrics")
                for item in samples:
                    conn.execute(
                        """INSERT INTO metrics
                           (node_id, model_name, version, metric, value, timestamp)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            item["node_id"],
                            item["model_name"],
                            item["version"],
                            item["metric"],
                            float(item["value"]),
                            item["timestamp"],
                        ),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def fetch_samples(
        self,
        *,
        model_name: str | None = None,
        version: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """저장된 메트릭 행을 조회한다."""
        clauses: list[str] = []
        params: list[Any] = []
        if model_name:
            clauses.append("model_name = ?")
            params.append(model_name)
        if version:
            clauses.append("version = ?")
            params.append(version)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        lim = f" LIMIT {int(limit)}" if limit else ""
        sql = (
            "SELECT node_id, model_name, version, metric, value, timestamp "
            f"FROM metrics {where} ORDER BY timestamp ASC{lim}"
        )
        with connect(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
