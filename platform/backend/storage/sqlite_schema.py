"""SQLite 스키마 정의 및 초기화."""
from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- models + versions (YAML: {name: {version: payload}})
CREATE TABLE IF NOT EXISTS model_versions (
    model_name TEXT NOT NULL,
    version TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (model_name, version)
);

CREATE TABLE IF NOT EXISTS silo_groups (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deployments (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS training_rounds (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 파라미터 기여 원장 (YAML: {round_id: {silo_id: payload}}) — 라운드×사일로 단위 upsert
CREATE TABLE IF NOT EXISTS contributions (
    round_id TEXT NOT NULL,
    silo_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (round_id, silo_id)
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    version TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_lookup
    ON metrics (model_name, version, metric, timestamp);

-- 자원 샘플 (resource_service 인메모리 창의 선택적 영속, 사일로당 최근 500개만 유지)
CREATE TABLE IF NOT EXISTS resource_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    silo_id TEXT NOT NULL,
    cpu_pct REAL,
    mem_pct REAL,
    gpu_pct REAL,
    disk_pct REAL,
    timestamp TEXT NOT NULL,
    measurement_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_resource_samples_silo
    ON resource_samples (silo_id, id);

CREATE TABLE IF NOT EXISTS resource_limits (
    node_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def apply_schema(conn: sqlite3.Connection) -> None:
    """스키마를 적용하고 migration 버전을 기록한다."""
    conn.executescript(DDL)
    _migrate_resource_samples(conn)
    # SELECT 후 INSERT는 신규 DB에 동시에 첫 연결이 들어오면 둘 다 빈 결과를 보고 INSERT해
    # UNIQUE 위반(IntegrityError)이 난다 — 멱등 INSERT로 한 문장에 끝낸다
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
        (SCHEMA_VERSION,),
    )


def _migrate_resource_samples(conn: sqlite3.Connection) -> None:
    """v1 표본을 보존하며 미지원(null)·측정 범위를 저장하도록 바꾼다."""
    columns = {row[1]: row for row in conn.execute("PRAGMA table_info(resource_samples)")}
    if "measurement_json" in columns and not columns["cpu_pct"][3]:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        # 동시에 첫 연결이 들어오더라도 잠금 취득 후 다시 검사한다.
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(resource_samples)")}
        if "measurement_json" not in columns or columns["cpu_pct"][3]:
            conn.execute("""CREATE TABLE resource_samples_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT, silo_id TEXT NOT NULL,
                cpu_pct REAL, mem_pct REAL, gpu_pct REAL, disk_pct REAL,
                timestamp TEXT NOT NULL, measurement_json TEXT NOT NULL DEFAULT '{}')""")
            metadata = "measurement_json" if "measurement_json" in columns else "'{}'"
            conn.execute(f"""INSERT INTO resource_samples_v2
                SELECT id, silo_id, cpu_pct, mem_pct, gpu_pct, disk_pct, timestamp,
                {metadata} FROM resource_samples""")
            conn.execute("DROP TABLE resource_samples")
            conn.execute("ALTER TABLE resource_samples_v2 RENAME TO resource_samples")
            conn.execute("CREATE INDEX idx_resource_samples_silo ON resource_samples(silo_id, id)")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
