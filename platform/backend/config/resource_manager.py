"""리소스 임계값 영속화 (사용률 샘플은 인메모리 휘발)"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from storage.factory import StorageDomain, get_repository

from .settings import CONFIG_DIR
from .yaml_store import load_yaml, save_yaml_atomic

logger = logging.getLogger(__name__)

RESOURCE_LIMITS_FILE: Path = CONFIG_DIR / "resource_limits.yaml"


def _load(path: Path) -> dict[str, Any]:
    return load_yaml(path)


def load_resource_limits() -> dict[str, Any]:
    return get_repository(StorageDomain.RESOURCE_LIMITS, RESOURCE_LIMITS_FILE).load()


def save_resource_limits(data: dict[str, Any]) -> None:
    get_repository(StorageDomain.RESOURCE_LIMITS, RESOURCE_LIMITS_FILE).save(data)
