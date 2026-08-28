"""YAML config → SQLite import 경로."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config.yaml_store import load_yaml

from .factory import StorageDomain, reset_repositories
from .settings import get_sqlite_path
from .sqlite_repository import SqliteMetricsRepository
from .sqlite_store import connect

logger = logging.getLogger(__name__)

# CONFIG_DIR 기준 YAML 파일명
_YAML_SOURCES: dict[StorageDomain, str] = {
    StorageDomain.MODELS: "models.yaml",
    StorageDomain.DEPLOYMENTS: "deployments.yaml",
    StorageDomain.SILO_GROUPS: "silo_groups.yaml",
    StorageDomain.TRAINING_ROUNDS: "training_rounds.yaml",
    StorageDomain.RESOURCE_LIMITS: "resource_limits.yaml",
    StorageDomain.ALERTS: "alerts.yaml",
}


def import_yaml_to_sqlite(
    config_dir: Path | None = None,
    *,
    db_path: Path | None = None,
    metric_samples: list[dict[str, Any]] | None = None,
) -> Path:
    """기존 YAML 스냅샷을 SQLite DB로 가져온다.

    Returns:
        생성/갱신된 DB 파일 경로
    """
    from .factory import build_sqlite_repository

    if config_dir is None:
        from config.settings import CONFIG_DIR

        config_dir = CONFIG_DIR
    config_dir = Path(config_dir)
    target_db = Path(db_path or get_sqlite_path())

    reset_repositories()
    imported: list[str] = []

    for domain, filename in _YAML_SOURCES.items():
        yaml_path = config_dir / filename
        data = load_yaml(yaml_path)
        if not data:
            continue
        repo = build_sqlite_repository(domain, target_db)
        repo.save(data)
        imported.append(f"{domain.value}({len(data)})")
        logger.info("imported %s from %s", domain.value, yaml_path)

    if metric_samples:
        metrics_repo = SqliteMetricsRepository(target_db)
        metrics_repo.replace_all(metric_samples)
        imported.append(f"metrics({len(metric_samples)})")

    with connect(target_db) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO schema_migrations (version) VALUES (1)"
        )

    logger.info("YAML→SQLite 완료: %s — %s", target_db, ", ".join(imported) or "(empty)")
    reset_repositories()
    return target_db
