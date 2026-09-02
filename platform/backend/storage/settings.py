"""저장소 백엔드 및 SQLite 경로 정책."""
from __future__ import annotations

import os
from pathlib import Path

from config import settings as config_settings

# yaml(기본) | sqlite — 하위 호환을 위해 기본값은 yaml
_VALID_BACKENDS = frozenset({"yaml", "sqlite"})


def get_backend() -> str:
    """활성 저장소 백엔드를 반환한다.

    우선순위: FED_STORAGE > FED_STORAGE_BACKEND (기본 yaml).
    """
    raw = (
        os.getenv("FED_STORAGE")
        or os.getenv("FED_STORAGE_BACKEND")
        or "yaml"
    ).strip().lower()
    return raw if raw in _VALID_BACKENDS else "yaml"


def get_sqlite_path() -> Path:
    """SQLite DB 파일 경로.

    우선순위: FED_SQLITE_PATH > FED_CONFIG_DIR/fed_platform.db
    """
    # CONFIG_DIR는 모듈 로드 시 복사하지 않고 매번 읽는다 — 테스트가 config.settings.CONFIG_DIR를
    # 격리 경로로 바꿔도 SQLite 파일이 실제 config/ 로 새지 않도록
    config_dir = config_settings.CONFIG_DIR
    explicit = os.getenv("FED_SQLITE_PATH")
    if explicit:
        path = Path(explicit).expanduser()
        return path.resolve() if path.is_absolute() else (config_dir / path).resolve()
    return (config_dir / "fed_platform.db").resolve()
