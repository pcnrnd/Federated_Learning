"""데이터 정제 영속화 (레시피 + 잡)"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .settings import CONFIG_DIR
from .yaml_store import load_yaml, save_yaml_atomic

logger = logging.getLogger(__name__)

RECIPES_FILE: Path = CONFIG_DIR / "cleaning_recipes.yaml"
JOBS_FILE: Path = CONFIG_DIR / "cleaning_jobs.yaml"


def _load(path: Path) -> dict[str, Any]:
    return load_yaml(path)


def _save(path: Path, data: dict[str, Any]) -> None:
    save_yaml_atomic(path, data)


def load_recipes() -> dict[str, Any]:
    """{name: {version: recipe-dict}}"""
    return _load(RECIPES_FILE)


def save_recipes(data: dict[str, Any]) -> None:
    _save(RECIPES_FILE, data)


def load_jobs() -> dict[str, Any]:
    return _load(JOBS_FILE)


def save_jobs(data: dict[str, Any]) -> None:
    _save(JOBS_FILE, data)
