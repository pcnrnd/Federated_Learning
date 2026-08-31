"""모니터링 영속화 (베이스라인/알림/감사 로그)"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from storage.factory import StorageDomain, get_repository

from .settings import CONFIG_DIR
from .yaml_store import load_yaml, save_yaml_atomic

logger = logging.getLogger(__name__)

BASELINES_FILE: Path = CONFIG_DIR / "baselines.yaml"
ALERT_RULES_FILE: Path = CONFIG_DIR / "alert_rules.yaml"
ALERTS_FILE: Path = CONFIG_DIR / "alerts.yaml"
AUDIT_LOG_FILE: Path = CONFIG_DIR / "audit.log"


def _load(path: Path) -> dict[str, Any]:
    return load_yaml(path)


def _save(path: Path, data: dict[str, Any]) -> None:
    save_yaml_atomic(path, data)


def load_baselines() -> dict[str, Any]:
    return _load(BASELINES_FILE)


def save_baselines(data: dict[str, Any]) -> None:
    _save(BASELINES_FILE, data)


def load_alert_rules() -> dict[str, Any]:
    return _load(ALERT_RULES_FILE)


def save_alert_rules(data: dict[str, Any]) -> None:
    _save(ALERT_RULES_FILE, data)


def load_alerts() -> dict[str, Any]:
    return get_repository(StorageDomain.ALERTS, ALERTS_FILE).load()


def save_alerts(data: dict[str, Any]) -> None:
    get_repository(StorageDomain.ALERTS, ALERTS_FILE).save(data)


def append_audit(line: str) -> None:
    AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def read_audit(tail: int | None = None) -> list[str]:
    if not AUDIT_LOG_FILE.exists():
        return []
    with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f.readlines()]
    return lines[-tail:] if tail else lines
