"""연합학습 메타 YAML 영속화 (사일로 그룹 / 학습 라운드 / 파라미터 기여)"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from storage.factory import StorageDomain, get_repository

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


def load_contributions() -> dict[str, Any]:
    """{round_id: {silo_id: {sample_count, parameters, ...}}}"""
    return _load(CONTRIBUTIONS_FILE)


def save_contributions(data: dict[str, Any]) -> None:
    _save(CONTRIBUTIONS_FILE, data)


def load_training_jobs() -> dict[str, Any]:
    return _load(TRAINING_JOBS_FILE)


def save_training_jobs(data: dict[str, Any]) -> None:
    _save(TRAINING_JOBS_FILE, data)
