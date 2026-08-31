"""저장소 백엔드별 Repository 팩토리."""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from .repository import DictRepository
from .settings import get_backend, get_sqlite_path
from .sqlite_repository import (
    SqliteFlatRepository,
    SqliteMetricsRepository,
    SqliteModelsRepository,
)
from .yaml_repository import YamlDictRepository

_repositories: dict[tuple[str, str], DictRepository] = {}


class StorageDomain(str, Enum):
    """Phase 1 핵심 도메인."""

    MODELS = "models"
    DEPLOYMENTS = "deployments"
    SILO_GROUPS = "silo_groups"
    TRAINING_ROUNDS = "training_rounds"
    METRICS = "metrics"
    RESOURCE_LIMITS = "resource_limits"
    ALERTS = "alerts"


def reset_repositories() -> None:
    """테스트 격리용 — 캐시된 Repository 인스턴스를 비운다."""
    _repositories.clear()


def get_repository(domain: StorageDomain, yaml_path: Path) -> DictRepository:
    """도메인 + YAML 경로로 Repository를 반환 (백엔드는 환경 변수)."""
    backend = get_backend()
    cache_key = (backend, domain.value)
    if cache_key in _repositories:
        return _repositories[cache_key]

    if backend == "sqlite":
        db_path = get_sqlite_path()
        repo = _build_sqlite(domain, db_path)
    else:
        repo = YamlDictRepository(yaml_path)

    _repositories[cache_key] = repo
    return repo


def build_sqlite_repository(domain: StorageDomain, db_path: Path) -> DictRepository:
    """지정 DB 경로에 SQLite Repository를 생성한다 (마이그레이션/테스트용)."""
    return _build_sqlite(domain, db_path)


def _build_sqlite(domain: StorageDomain, db_path: Path) -> DictRepository:
    if domain == StorageDomain.MODELS:
        return SqliteModelsRepository(db_path)
    if domain == StorageDomain.METRICS:
        return SqliteMetricsRepository(db_path)
    table_map = {
        StorageDomain.DEPLOYMENTS: ("deployments", "id"),
        StorageDomain.SILO_GROUPS: ("silo_groups", "id"),
        StorageDomain.TRAINING_ROUNDS: ("training_rounds", "id"),
        StorageDomain.RESOURCE_LIMITS: ("resource_limits", "node_id"),
        StorageDomain.ALERTS: ("alerts", "id"),
    }
    table, id_col = table_map[domain]
    return SqliteFlatRepository(db_path, table=table, id_column=id_col)
