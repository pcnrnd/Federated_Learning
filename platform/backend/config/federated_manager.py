"""연합학습 메타 YAML 영속화 (사일로 그룹 / 학습 라운드 / 파라미터 기여)"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from storage.factory import StorageDomain, get_repository
from storage.settings import get_backend

from .settings import CONFIG_DIR
from .yaml_store import load_yaml, save_yaml_atomic

logger = logging.getLogger(__name__)

SILO_GROUPS_FILE: Path = CONFIG_DIR / "silo_groups.yaml"
TRAINING_ROUNDS_FILE: Path = CONFIG_DIR / "training_rounds.yaml"
CONTRIBUTIONS_FILE: Path = CONFIG_DIR / "contributions.yaml"
TRAINING_JOBS_FILE: Path = CONFIG_DIR / "training_jobs.yaml"


def _load(path: Path) -> dict[str, Any]:
    return load_yaml(path)


def _save(path: Path, data: dict[str, Any]) -> None:
    save_yaml_atomic(path, data)


def load_silo_groups() -> dict[str, Any]:
    return get_repository(StorageDomain.SILO_GROUPS, SILO_GROUPS_FILE).load()


def save_silo_groups(data: dict[str, Any]) -> None:
    get_repository(StorageDomain.SILO_GROUPS, SILO_GROUPS_FILE).save(data)


def load_training_rounds() -> dict[str, Any]:
    return get_repository(StorageDomain.TRAINING_ROUNDS, TRAINING_ROUNDS_FILE).load()


def save_training_rounds(data: dict[str, Any]) -> None:
    get_repository(StorageDomain.TRAINING_ROUNDS, TRAINING_ROUNDS_FILE).save(data)


def get_training_round(round_id: str) -> dict[str, Any] | None:
    return get_repository(StorageDomain.TRAINING_ROUNDS, TRAINING_ROUNDS_FILE).get(round_id)


def upsert_training_round(round_id: str, payload: dict[str, Any]) -> None:
    """라운드 1건 저장 — 전체 라운드 이력을 다시 쓰지 않는다."""
    get_repository(StorageDomain.TRAINING_ROUNDS, TRAINING_ROUNDS_FILE).upsert(round_id, payload)


# ---------- 파라미터 기여 원장 {round_id: {silo_id: {sample_count, parameters, ...}}} ----------

_legacy_cache: tuple[int, dict[str, Any]] | None = None  # (mtime_ns, 내용)


def _legacy_contributions() -> dict[str, Any]:
    """SQLite 전환 이전 contributions.yaml — 무손실 dual-read용 읽기 전용 스냅샷.

    SQLite 경로는 이 파일을 다시 쓰지 않으므로 mtime이 같으면 캐시를 재사용한다
    (미스마다 수백 KB YAML을 다시 파싱하면 tick 비용이 다시 O(n)이 된다).
    """
    global _legacy_cache
    try:
        mtime = CONTRIBUTIONS_FILE.stat().st_mtime_ns
    except OSError:
        return {}
    if _legacy_cache is None or _legacy_cache[0] != mtime:
        _legacy_cache = (mtime, load_yaml(CONTRIBUTIONS_FILE))
        logger.info("legacy contributions.yaml dual-read 로드: %d라운드", len(_legacy_cache[1]))
    return _legacy_cache[1]


def load_round_contributions(round_id: str) -> dict[str, Any]:
    """라운드 1건의 기여 {silo_id: record}.

    SQLite 백엔드에서는 legacy contributions.yaml의 같은 라운드 기여와 **병합**해 돌려준다
    (silo_id가 겹치면 SQLite 우선). "SQLite 버킷이 비었을 때만 YAML"로 하면 YAML 기여가
    있는 라운드에 새 SQLite 기여가 하나 들어오는 순간 기존 기여가 가려져 라운드 정체·중복
    재수락이 생긴다 (리뷰 재현: [silo-old] → [silo-new]). 새 기여는 SQLite에만 쓰이므로
    `scripts/migrate_yaml_to_sqlite.py`를 돌리지 않고 전환해도 무손실이다.
    """
    bucket = get_repository(StorageDomain.CONTRIBUTIONS, CONTRIBUTIONS_FILE).load_round(round_id)
    if get_backend() != "sqlite":
        return bucket
    legacy = _legacy_contributions().get(round_id)
    if not isinstance(legacy, dict):
        return bucket
    return {**legacy, **bucket}


def upsert_contribution(round_id: str, silo_id: str, record: dict[str, Any]) -> None:
    get_repository(StorageDomain.CONTRIBUTIONS, CONTRIBUTIONS_FILE).upsert(
        round_id, silo_id, record
    )


def load_training_jobs() -> dict[str, Any]:
    return _load(TRAINING_JOBS_FILE)


def save_training_jobs(data: dict[str, Any]) -> None:
    _save(TRAINING_JOBS_FILE, data)
