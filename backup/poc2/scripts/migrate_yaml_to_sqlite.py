#!/usr/bin/env python3
"""YAML config 디렉토리를 SQLite DB로 마이그레이션한다.

사용 예:
  cd app
  FED_STORAGE_BACKEND=sqlite python scripts/migrate_yaml_to_sqlite.py
  FED_CONFIG_DIR=../config FED_SQLITE_PATH=../config/fed_platform.db python scripts/migrate_yaml_to_sqlite.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from storage.migration import import_yaml_to_sqlite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="YAML → SQLite import")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="YAML 소스 디렉토리 (기본: FED_CONFIG_DIR 또는 repo/config)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="대상 SQLite 파일 (기본: FED_SQLITE_PATH 또는 config/fed_platform.db)",
    )
    args = parser.parse_args()

    os.environ.setdefault("FED_STORAGE_BACKEND", "sqlite")
    db_path = import_yaml_to_sqlite(args.config_dir, db_path=args.db_path)
    print(f"마이그레이션 완료: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
