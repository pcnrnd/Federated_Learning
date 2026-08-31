"""pytest 공용 설정"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent  # app/tests/conftest.py → app/
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """각 테스트에 대해 config 디렉토리를 임시 경로로 격리"""
    import config.settings as settings_mod
    import config.registry_manager as reg_mod
    import config.server_manager as srv_mod
    import config.monitoring_manager as mon_mod
    import config.federated_manager as fed_mod
    import config.resource_manager as res_mod
    import config.maintenance_manager as maint_mod
    import config.cleaning_manager as cln_mod
    import storage.settings as storage_settings
    from services import metric_store, resource_service
    from services import idempotency
    from storage.factory import reset_repositories

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    db_path = config_dir / "fed_platform.db"
    monkeypatch.setattr(settings_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(storage_settings, "get_sqlite_path", lambda: db_path)
    monkeypatch.delenv("FED_STORAGE_BACKEND", raising=False)
    reset_repositories()
    monkeypatch.setattr(settings_mod, "SERVERS_FILE", config_dir / "servers.yaml")
    monkeypatch.setattr(reg_mod, "MODELS_FILE", config_dir / "models.yaml")
    monkeypatch.setattr(reg_mod, "DEPLOYMENTS_FILE", config_dir / "deployments.yaml")
    monkeypatch.setattr(srv_mod, "SERVERS_FILE", config_dir / "servers.yaml")
    monkeypatch.setattr(mon_mod, "BASELINES_FILE", config_dir / "baselines.yaml")
    monkeypatch.setattr(mon_mod, "ALERT_RULES_FILE", config_dir / "alert_rules.yaml")
    monkeypatch.setattr(mon_mod, "ALERTS_FILE", config_dir / "alerts.yaml")
    monkeypatch.setattr(mon_mod, "AUDIT_LOG_FILE", config_dir / "audit.log")
    monkeypatch.setattr(fed_mod, "SILO_GROUPS_FILE", config_dir / "silo_groups.yaml")
    monkeypatch.setattr(fed_mod, "TRAINING_ROUNDS_FILE", config_dir / "training_rounds.yaml")
    monkeypatch.setattr(fed_mod, "CONTRIBUTIONS_FILE", config_dir / "contributions.yaml")
    monkeypatch.setattr(fed_mod, "TRAINING_JOBS_FILE", config_dir / "training_jobs.yaml")
    monkeypatch.setattr(res_mod, "RESOURCE_LIMITS_FILE", config_dir / "resource_limits.yaml")
    monkeypatch.setattr(maint_mod, "LINEAGE_FILE", config_dir / "lineage.yaml")
    monkeypatch.setattr(maint_mod, "SHADOWS_FILE", config_dir / "shadow_deployments.yaml")
    monkeypatch.setattr(maint_mod, "AB_TESTS_FILE", config_dir / "ab_tests.yaml")
    monkeypatch.setattr(cln_mod, "RECIPES_FILE", config_dir / "cleaning_recipes.yaml")
    monkeypatch.setattr(cln_mod, "JOBS_FILE", config_dir / "cleaning_jobs.yaml")
    metric_store.clear()
    resource_service.clear_samples()
    idempotency.clear()
    yield
    reset_repositories()
    metric_store.clear()
    resource_service.clear_samples()
    idempotency.clear()
