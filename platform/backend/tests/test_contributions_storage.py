"""기여 원장·라운드 단건 upsert — YAML↔SQLite 동등성, 원자성, legacy 마이그레이션/dual-read 테스트."""
from __future__ import annotations

import threading

import pytest

from config import federated_manager
from config.yaml_store import load_yaml, save_yaml_atomic
from storage.factory import StorageDomain, build_sqlite_repository, reset_repositories
from storage.migration import import_yaml_to_sqlite
from storage.sqlite_repository import SqliteContributionsRepository, SqliteFlatRepository
from storage.yaml_repository import YamlContributionsRepository, YamlDictRepository


def _record(silo: str, n: int) -> dict:
    return {"silo_id": silo, "sample_count": n, "parameters": [1.0, 2.0], "aggregated_from": []}


def _apply_ledger_ops(repo) -> None:
    repo.upsert("r1", "silo-1", _record("silo-1", 10))
    repo.upsert("r1", "silo-2", _record("silo-2", 20))
    repo.upsert("r2", "silo-1", _record("silo-1", 30))
    repo.upsert("r1", "silo-1", _record("silo-1", 11))  # 갱신


# ---------- 동등성 ----------


@pytest.mark.unit
def test_contributions_yaml_and_sqlite_produce_identical_ledgers(tmp_path):
    yaml_repo = YamlContributionsRepository(tmp_path / "contributions.yaml")
    sqlite_repo = SqliteContributionsRepository(tmp_path / "db.sqlite")

    _apply_ledger_ops(yaml_repo)
    _apply_ledger_ops(sqlite_repo)

    expected = {
        "r1": {"silo-1": _record("silo-1", 11), "silo-2": _record("silo-2", 20)},
        "r2": {"silo-1": _record("silo-1", 30)},
    }
    assert yaml_repo.load() == expected == sqlite_repo.load()
    assert yaml_repo.load_round("r1") == expected["r1"] == sqlite_repo.load_round("r1")
    assert yaml_repo.load_round("missing") == {} == sqlite_repo.load_round("missing")


@pytest.mark.unit
def test_flat_get_upsert_yaml_and_sqlite_equivalent(tmp_path):
    yaml_repo = YamlDictRepository(tmp_path / "rounds.yaml")
    sqlite_repo = SqliteFlatRepository(tmp_path / "db.sqlite", table="training_rounds")

    for repo in (yaml_repo, sqlite_repo):
        repo.save({"a": {"status": "open"}, "b": {"status": "open"}})
        repo.upsert("a", {"status": "completed"})
        repo.upsert("c", {"status": "open"})

    expected = {"a": {"status": "completed"}, "b": {"status": "open"}, "c": {"status": "open"}}
    assert yaml_repo.load() == expected == sqlite_repo.load()
    assert yaml_repo.get("a") == {"status": "completed"} == sqlite_repo.get("a")
    assert yaml_repo.get("zzz") is None and sqlite_repo.get("zzz") is None


@pytest.mark.unit
def test_contributions_save_roundtrip_matches_upsert_ledger(tmp_path):
    """save(전체) → load 가 upsert로 쌓은 원장과 같아야 마이그레이션이 무손실이다."""
    source = SqliteContributionsRepository(tmp_path / "a.sqlite")
    _apply_ledger_ops(source)
    target = SqliteContributionsRepository(tmp_path / "b.sqlite")

    target.save(source.load())

    assert target.load() == source.load()


# ---------- 원자성 ----------


@pytest.mark.unit
def test_sqlite_upsert_serialization_failure_leaves_ledger_intact(tmp_path, monkeypatch):
    repo = SqliteContributionsRepository(tmp_path / "db.sqlite")
    repo.upsert("r1", "silo-1", _record("silo-1", 1))

    monkeypatch.setattr(
        "storage.sqlite_repository._json_dump",
        lambda _v: (_ for _ in ()).throw(ValueError("serialize fail")),
    )
    with pytest.raises(ValueError):
        repo.upsert("r1", "silo-2", _record("silo-2", 2))
    monkeypatch.undo()

    assert repo.load() == {"r1": {"silo-1": _record("silo-1", 1)}}


@pytest.mark.unit
def test_sqlite_flat_upsert_does_not_touch_other_rows(tmp_path):
    repo = SqliteFlatRepository(tmp_path / "db.sqlite", table="training_rounds")
    repo.save({f"r{i}": {"i": i} for i in range(5)})

    repo.upsert("r2", {"i": 200})

    loaded = repo.load()
    assert loaded["r2"] == {"i": 200}
    assert {k: v for k, v in loaded.items() if k != "r2"} == {
        f"r{i}": {"i": i} for i in range(5) if i != 2
    }


@pytest.mark.unit
def test_concurrent_contribution_upserts_all_land(tmp_path):
    repo = SqliteContributionsRepository(tmp_path / "db.sqlite")
    errors: list[Exception] = []

    def writer(silo: str) -> None:
        try:
            for i in range(20):
                repo.upsert(f"r{i}", silo, _record(silo, i))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(f"silo-{n}",)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    ledger = repo.load()
    assert len(ledger) == 20 and all(len(bucket) == 4 for bucket in ledger.values())


# ---------- legacy contributions.yaml 마이그레이션 + dual-read ----------


@pytest.fixture
def sqlite_backend(monkeypatch):
    import config.settings as settings_mod

    db_path = settings_mod.CONFIG_DIR / "fed_platform.db"
    monkeypatch.setenv("FED_STORAGE", "sqlite")
    monkeypatch.setattr(federated_manager, "_legacy_cache", None)
    reset_repositories()
    yield settings_mod.CONFIG_DIR, db_path
    reset_repositories()


@pytest.mark.unit
def test_import_yaml_to_sqlite_carries_contributions_ledger(sqlite_backend):
    config_dir, db_path = sqlite_backend
    legacy = {"r-old": {"silo-1": _record("silo-1", 5), "silo-2": _record("silo-2", 6)}}
    save_yaml_atomic(config_dir / "contributions.yaml", legacy)

    import_yaml_to_sqlite(config_dir, db_path=db_path)

    assert build_sqlite_repository(StorageDomain.CONTRIBUTIONS, db_path).load() == legacy
    assert load_yaml(config_dir / "contributions.yaml") == legacy  # 원본 무손상


@pytest.mark.unit
def test_dual_read_falls_back_to_legacy_yaml_for_unmigrated_rounds(sqlite_backend):
    config_dir, _ = sqlite_backend
    legacy_path = federated_manager.CONTRIBUTIONS_FILE
    assert legacy_path.parent == config_dir
    save_yaml_atomic(legacy_path, {"r-old": {"silo-1": _record("silo-1", 5)}})

    # SQLite에 없는 라운드 → legacy YAML에서 읽힌다
    assert federated_manager.load_round_contributions("r-old") == {"silo-1": _record("silo-1", 5)}
    # 새 기여는 SQLite에만 쓰이고 legacy 파일은 그대로다
    federated_manager.upsert_contribution("r-new", "silo-2", _record("silo-2", 7))
    assert federated_manager.load_round_contributions("r-new") == {"silo-2": _record("silo-2", 7)}
    assert load_yaml(legacy_path) == {"r-old": {"silo-1": _record("silo-1", 5)}}
    # 미지 라운드는 양쪽 다 없음
    assert federated_manager.load_round_contributions("nope") == {}


@pytest.mark.unit
def test_dual_read_merges_same_round_yaml_and_sqlite_contributions(sqlite_backend):
    """회귀: YAML 기여가 있는 라운드에 SQLite 기여가 추가돼도 기존 YAML 기여가 가려지지 않는다."""
    legacy_path = federated_manager.CONTRIBUTIONS_FILE
    save_yaml_atomic(legacy_path, {"r-mixed": {"silo-old": _record("silo-old", 5)}})
    assert set(federated_manager.load_round_contributions("r-mixed")) == {"silo-old"}

    federated_manager.upsert_contribution("r-mixed", "silo-new", _record("silo-new", 7))

    merged = federated_manager.load_round_contributions("r-mixed")
    assert merged == {"silo-old": _record("silo-old", 5), "silo-new": _record("silo-new", 7)}
    # 중복 검사·집계 기준이 되는 개수도 양쪽 합
    assert len(merged) == 2


@pytest.mark.unit
def test_dual_read_sqlite_record_wins_on_silo_id_conflict(sqlite_backend):
    legacy_path = federated_manager.CONTRIBUTIONS_FILE
    save_yaml_atomic(legacy_path, {"r-dup": {"silo-1": _record("silo-1", 1)}})

    federated_manager.upsert_contribution("r-dup", "silo-1", _record("silo-1", 99))

    assert federated_manager.load_round_contributions("r-dup") == {"silo-1": _record("silo-1", 99)}


@pytest.mark.unit
def test_submit_contribution_rejects_duplicate_of_legacy_yaml_contribution(sqlite_backend, tmp_path):
    """서비스 경로 회귀: YAML에만 있는 기여도 중복(409)으로 막히고, 다른 사일로 기여 후에도 그대로 보인다."""
    from fastapi import HTTPException

    from config.server_manager import save_servers
    from models.federated_schemas import ParameterContribution, SiloGroupRequest, TrainingRoundCreate
    from models.packaging_schemas import ModelRegisterRequest
    from services import model_registry, silo_group_service, training_round_service

    save_servers({
        f"silo-{i}": {"base_url": f"tcp://localhost:237{i}", "label": f"silo-{i}",
                      "type": "remote", "role": "client", "tls": False}
        for i in (1, 2)
    })
    weights = tmp_path / "m.pt"
    weights.write_bytes(b"")
    model_registry.register_model(ModelRegisterRequest(
        name="alpha", version="1.0.0", framework="pytorch", weights_path=str(weights)))
    silo_group_service.create_group(SiloGroupRequest(group_id="g1", member_node_ids=["silo-1", "silo-2"]))
    rnd = training_round_service.create_round(
        TrainingRoundCreate(model_name="alpha", version="1.0.0", group_id="g1", min_contributions=2))
    # silo-1 기여는 SQLite 전환 전 YAML 원장에만 존재한다고 가정
    save_yaml_atomic(federated_manager.CONTRIBUTIONS_FILE, {rnd.round_id: {"silo-1": {
        "silo_id": "silo-1", "sample_count": 1, "parameters": [1.0, 1.0],
        "submitted_at": "2026-09-01T00:00:00+00:00", "checksum": None, "aggregated_from": []}}})

    with pytest.raises(HTTPException) as exc:
        training_round_service.submit_contribution(ParameterContribution(
            round_id=rnd.round_id, silo_id="silo-1", sample_count=1, parameters=[1.0, 1.0]))
    assert exc.value.status_code == 409

    training_round_service.submit_contribution(ParameterContribution(
        round_id=rnd.round_id, silo_id="silo-2", sample_count=3, parameters=[3.0, 3.0]))
    assert {r.silo_id for r in training_round_service.list_contributions(rnd.round_id)} == {"silo-1", "silo-2"}
    result = training_round_service.aggregate_round(rnd.round_id)
    assert result.contributor_count == 2 and result.total_samples == 4


@pytest.mark.unit
def test_dual_read_caches_legacy_until_file_changes(sqlite_backend, monkeypatch):
    legacy_path = federated_manager.CONTRIBUTIONS_FILE
    save_yaml_atomic(legacy_path, {"r-old": {"silo-1": _record("silo-1", 1)}})
    calls = {"n": 0}
    real_load = federated_manager.load_yaml

    def counting_load(path):
        calls["n"] += 1
        return real_load(path)

    monkeypatch.setattr(federated_manager, "load_yaml", counting_load)
    for _ in range(5):
        federated_manager.load_round_contributions("r-old")
    assert calls["n"] == 1  # 미스마다 재파싱하지 않는다


@pytest.mark.unit
def test_round_service_end_to_end_on_sqlite_backend(sqlite_backend, tmp_path):
    """sqlite 백엔드에서 라운드 생성 → 기여 2건 → 자동 집계 조건 → aggregate 까지 단건 upsert 경로로 동작."""
    from config.server_manager import save_servers
    from models.federated_schemas import ParameterContribution, SiloGroupRequest, TrainingRoundCreate
    from models.packaging_schemas import ModelRegisterRequest
    from services import model_registry, silo_group_service, training_round_service

    save_servers({
        f"silo-{i}": {"base_url": f"tcp://localhost:237{i}", "label": f"silo-{i}",
                      "type": "remote", "role": "client", "tls": False}
        for i in (1, 2)
    })
    weights = tmp_path / "m.pt"
    weights.write_bytes(b"")
    model_registry.register_model(ModelRegisterRequest(
        name="alpha", version="1.0.0", framework="pytorch", weights_path=str(weights)))
    silo_group_service.create_group(SiloGroupRequest(group_id="g1", member_node_ids=["silo-1", "silo-2"]))

    rnd = training_round_service.create_round(
        TrainingRoundCreate(model_name="alpha", version="1.0.0", group_id="g1", min_contributions=2))
    for silo, n, params in (("silo-1", 1, [1.0, 1.0]), ("silo-2", 3, [3.0, 3.0])):
        training_round_service.submit_contribution(ParameterContribution(
            round_id=rnd.round_id, silo_id=silo, sample_count=n, parameters=params))

    assert len(training_round_service.list_contributions(rnd.round_id)) == 2
    result = training_round_service.aggregate_round(rnd.round_id)
    assert result.parameters == [2.5, 2.5] and result.total_samples == 4
    assert training_round_service.get_round(rnd.round_id).status == "completed"
    # 라운드 원장·기여 원장 모두 SQLite에 있고 YAML 파일은 생기지 않았다
    _, db_path = sqlite_backend
    assert rnd.round_id in build_sqlite_repository(StorageDomain.TRAINING_ROUNDS, db_path).load()
    assert set(build_sqlite_repository(StorageDomain.CONTRIBUTIONS, db_path).load_round(rnd.round_id)) == {
        "silo-1", "silo-2"}
    assert not federated_manager.CONTRIBUTIONS_FILE.exists()
    assert not federated_manager.TRAINING_ROUNDS_FILE.exists()
