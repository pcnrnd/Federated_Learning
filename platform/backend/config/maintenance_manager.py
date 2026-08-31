"""유지관리(lineage / shadow / ab) YAML 영속화"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .settings import CONFIG_DIR
from .yaml_store import load_yaml, save_yaml_atomic

logger = logging.getLogger(__name__)

LINEAGE_FILE: Path = CONFIG_DIR / "lineage.yaml"
SHADOWS_FILE: Path = CONFIG_DIR / "shadow_deployments.yaml"
AB_TESTS_FILE: Path = CONFIG_DIR / "ab_tests.yaml"


def _load(path: Path) -> dict[str, Any]:
    return load_yaml(path)


def _save(path: Path, data: dict[str, Any]) -> None:
    save_yaml_atomic(path, data)


def load_lineage() -> dict[str, Any]:
    return _load(LINEAGE_FILE)


def save_lineage(data: dict[str, Any]) -> None:
    _save(LINEAGE_FILE, data)


def load_shadows() -> dict[str, Any]:
    return _load(SHADOWS_FILE)


def save_shadows(data: dict[str, Any]) -> None:
    _save(SHADOWS_FILE, data)


def load_ab_tests() -> dict[str, Any]:
    return _load(AB_TESTS_FILE)


def save_ab_tests(data: dict[str, Any]) -> None:
    _save(AB_TESTS_FILE, data)
