"""SQLite 연결 및 백업/복구 유틸."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from .sqlite_schema import apply_schema


def connect(db_path: Path, *, timeout: float = 30.0) -> sqlite3.Connection:
    """WAL 모드 SQLite 연결을 연다."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=timeout, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    apply_schema(conn)
    return conn


def backup_database(db_path: Path, dest: Path) -> None:
    """SQLite 온라인 백업 (Windows에서도 열린 DB 파일 복사 가능)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as src:
        with sqlite3.connect(str(dest)) as dest_conn:
            src.backup(dest_conn)


def restore_database(backup_path: Path, dest: Path) -> None:
    """백업 스냅샷을 기존 DB 파일 위에 복구한다 (Windows 파일 잠금 회피)."""
    with sqlite3.connect(str(backup_path)) as src:
        with connect(dest) as dest_conn:
            src.backup(dest_conn)

