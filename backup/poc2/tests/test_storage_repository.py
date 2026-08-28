"""Repository / SQLite migration / 동시성·복구 테스트."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from config.yaml_store import load_yaml, save_yaml_atomic
from storage.factory import StorageDomain, get_repository, reset_repositories
from storage.migration import import_yaml_to_sqlite
from storage.settings import get_sqlite_path
from storage.sqlite_store import backup_database, restore_database
from storage.yaml_repository import YamlDictRepository


@pytest.fixture
def storage_env(monkeypatch):
    """conftest 격리 config에 SQLite 경로를 맞춘다."""
    import config.settings as settings_mod
    import storage.settings as storage_settings

    config_dir = settings_mod.CONFIG_DIR
    db_path = config_dir / "fed_platform.db"
    monkeypatch.setattr(storage_settings, "get_sqlite_path", lambda: db_path)
    monkeypatch.setenv("FED_STORAGE_BACKEND", "yaml")
    reset_repositories()
    yield config_dir, db_path
    reset_repositories()


def test_yaml_repository_roundtrip(tmp_path):
    path = tmp_path / "data.yaml"
    repo = YamlDictRepository(path)
    repo.save({"a": {"k": 1}})
    assert repo.load() == {"a": {"k": 1}}


def test_save_yaml_atomic_no_stale_tmp_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "ok.yaml"
    save_yaml_atomic(path, {"v": 1})

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr("config.yaml_store.os.replace", _boom)
    with pytest.raises(OSError):
        save_yaml_atomic(path, {"v": 2})
    assert load_yaml(path) == {"v": 1}
    assert list(tmp_path.glob("*.tmp")) == []


def test_sqlite_models_repository_roundtrip(storage_env, monkeypatch):
    config_dir, db_path = storage_env
    monkeypatch.setenv("FED_STORAGE_BACKEND", "sqlite")
    reset_repositories()
    # import는 sqlite에 쓰고, load도 sqlite 백엔드를 사용해야 한다

    save_yaml_atomic(
        config_dir / "models.yaml",
        {"m1": {"1.0.0": {"framework": "pytorch"}}},
    )
    import_yaml_to_sqlite(config_dir, db_path=db_path)

    from storage.factory import build_sqlite_repository

    repo = build_sqlite_repository(StorageDomain.MODELS, db_path)
    loaded = repo.load()
    assert loaded["m1"]["1.0.0"]["framework"] == "pytorch"

    loaded["m1"]["2.0.0"] = {"framework": "onnx"}
    repo.save(loaded)
    again = build_sqlite_repository(StorageDomain.MODELS, db_path).load()
    assert "2.0.0" in again["m1"]


def test_concurrent_sqlite_writes(storage_env):
    _, db_path = storage_env
    errors: list[Exception] = []

    def writer(prefix: str) -> None:
        try:
            repo = __import__(
                "storage.factory", fromlist=["build_sqlite_repository"]
            ).build_sqlite_repository(StorageDomain.ALERTS, db_path)
            repo.save({f"{prefix}-{i}": {"n": i} for i in range(20)})
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(f"t{idx}",)) for idx in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    from storage.factory import build_sqlite_repository

    # 동시 DELETE+INSERT 경쟁에서도 예외 없이 완료되는지가 목적
    build_sqlite_repository(StorageDomain.ALERTS, db_path).load()


def test_sqlite_transaction_rollback_on_failure(storage_env, monkeypatch):
    _, db_path = storage_env
    from storage.sqlite_repository import SqliteFlatRepository

    repo = SqliteFlatRepository(db_path, table="alerts", id_column="id")
    repo.save({"a": {"x": 1}})

    original = __import__("json").dumps

    def _broken_dump(value, *args, **kwargs):
        if value is True:
            raise ValueError("serialize fail")
        return original(value, *args, **kwargs)

    monkeypatch.setattr("storage.sqlite_repository._json_dump", _broken_dump)
    with pytest.raises(ValueError):
        repo.save({"bad-key": True, "ok": {"y": 2}})

    assert repo.load() == {"a": {"x": 1}}


def test_backup_and_restore_sqlite(storage_env):
    _, db_path = storage_env
    from storage.factory import build_sqlite_repository
    from storage.sqlite_store import connect

    repo = build_sqlite_repository(StorageDomain.DEPLOYMENTS, db_path)
    repo.save({"d1": {"status": "running"}})

    backup_path = db_path.parent / "backup.db"
    backup_database(db_path, backup_path)

    repo.save({})
    assert repo.load() == {}

    restore_database(backup_path, db_path)
    reset_repositories()
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload FROM deployments WHERE id = 'd1'"
        ).fetchone()
    assert row is not None
    import json

    assert json.loads(row["payload"]) == {"status": "running"}


def test_import_yaml_to_sqlite_all_domains(storage_env):
    config_dir, db_path = storage_env
    save_yaml_atomic(config_dir / "models.yaml", {"m": {"1.0.0": {}}})
    save_yaml_atomic(config_dir / "deployments.yaml", {"dep-1": {}})
    save_yaml_atomic(config_dir / "silo_groups.yaml", {"g1": {}})
    save_yaml_atomic(config_dir / "training_rounds.yaml", {"r1": {}})
    save_yaml_atomic(config_dir / "resource_limits.yaml", {"node-a": {}})
    save_yaml_atomic(config_dir / "alerts.yaml", {"alert-1": {}})

    import_yaml_to_sqlite(config_dir, db_path=db_path)

    from storage.factory import build_sqlite_repository

    assert build_sqlite_repository(StorageDomain.MODELS, db_path).load()["m"]["1.0.0"] == {}
    assert "dep-1" in build_sqlite_repository(StorageDomain.DEPLOYMENTS, db_path).load()
    assert "g1" in build_sqlite_repository(StorageDomain.SILO_GROUPS, db_path).load()
    assert "r1" in build_sqlite_repository(StorageDomain.TRAINING_ROUNDS, db_path).load()
    assert "node-a" in build_sqlite_repository(StorageDomain.RESOURCE_LIMITS, db_path).load()
    assert "alert-1" in build_sqlite_repository(StorageDomain.ALERTS, db_path).load()


def test_default_backend_is_yaml(storage_env, monkeypatch):
    config_dir, db_path = storage_env
    monkeypatch.delenv("FED_STORAGE", raising=False)
    monkeypatch.setenv("FED_STORAGE_BACKEND", "yaml")
    reset_repositories()
    models_path = config_dir / "models.yaml"
    save_yaml_atomic(models_path, {"x": {"1.0.0": {"f": 1}}})

    repo = get_repository(StorageDomain.MODELS, models_path)
    assert repo.load()["x"]["1.0.0"]["f"] == 1
    assert db_path.name == "fed_platform.db"


def test_fed_storage_env_alias(monkeypatch):
    """FED_STORAGE가 FED_STORAGE_BACKEND보다 우선한다."""
    from storage.settings import get_backend

    monkeypatch.setenv("FED_STORAGE", "sqlite")
    monkeypatch.setenv("FED_STORAGE_BACKEND", "yaml")
    assert get_backend() == "sqlite"
    monkeypatch.delenv("FED_STORAGE", raising=False)
    assert get_backend() == "yaml"
