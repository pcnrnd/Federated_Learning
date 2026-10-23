"""G5-A: 실제 전략·영속 저장, Docker/endpoint 경계 대역. 이미지/HTTP 실검증은 runtime 시험."""
import importlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from docker.errors import DockerException
from fastapi import BackgroundTasks, HTTPException, Response
from pydantic import ValidationError

from g5_helpers import IMAGE, request, setup_world
from services import deployment_service as service
from storage.factory import reset_repositories


@pytest.fixture(params=["yaml", "sqlite"])
def world(tmp_path, monkeypatch, request):
    monkeypatch.setenv("FED_STORAGE", request.param)
    reset_repositories()
    return setup_world(tmp_path, monkeypatch)


def test_target_identity_env_port_and_verification_are_required(world):
    entry = service.create_deployment(request(inference_port=8600))
    assert entry.status == "running" and entry.verified_at and not entry.launch_pending
    assert set(entry.target_results) == {"silo-1", "silo-2"}
    for client in world.clients.values():
        created = client.containers.creates[0]
        assert created["image"] == IMAGE and created["environment"] == {"APP_SETTING": "preserved=value"}
        assert created["ports"] == {"8600/tcp": None}
        assert created["command"][-1] == "8600" and "8600" in created["healthcheck"]["test"][-1]
    assert all(result.image_id == IMAGE and result.verified_at for result in entry.target_results.values())


def test_one_failed_target_does_not_skip_others_or_report_success(world):
    world.failed.add("silo-1")
    entry = service.create_deployment(request())
    assert entry.status == "failed" and entry.launch_pending and not entry.verified_at
    assert entry.target_results["silo-1"].status == "failed"
    assert entry.target_results["silo-2"].status == "running"
    assert len(world.verified) == 2 and all(len(c.containers.creates) == 1 for c in world.clients.values())
    world.failed.clear()
    retried = service.retry_deployment(entry.deployment_id)
    assert retried.status == "running" and retried.verified_at
    assert all(len(c.containers.creates) == 1 for c in world.clients.values())


def test_same_request_same_settings_reload_and_concurrent_retry_reuse_but_new_command_is_new(world):
    req = request(request_id="command-one")
    first = service.create_deployment(req, defer=True)
    importlib.reload(service)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _n: service.create_deployment(req, defer=True), range(2)))
    assert {entry.deployment_id for entry in results} == {first.deployment_id}
    assert len(service.list_deployments()) == 1
    with pytest.raises(HTTPException) as mismatch:
        service.create_deployment(request(request_id="command-one", env={"APP_SETTING": "different"}), defer=True)
    assert mismatch.value.status_code == 409
    second = service.create_deployment(request(request_id="new-user-command"), defer=True)
    assert second.deployment_id != first.deployment_id and len(service.list_deployments()) == 2


@pytest.mark.parametrize("after_write", [False, True])
def test_request_pending_save_failure_has_no_docker_and_same_id_recovers(world, monkeypatch, after_write):
    original = service._save
    def failing(entry):
        if after_write:
            original(entry)
        raise OSError("injected response lost")
    monkeypatch.setattr(service, "_save", failing)
    with pytest.raises(OSError):
        service.create_deployment(request(request_id="durable-request"), defer=True)
    assert all(not c.containers.creates for c in world.clients.values())
    saved = service.list_deployments()
    monkeypatch.setattr(service, "_save", original)
    recovered = service.create_deployment(request(request_id="durable-request"), defer=True)
    assert len(service.list_deployments()) == 1
    if saved:
        assert recovered.deployment_id == saved[0].deployment_id


def test_api_reserves_before_background_and_retry_of_pending_uses_same_id(world):
    from api.deployments import create_deployment_endpoint
    tasks = BackgroundTasks()
    entry = create_deployment_endpoint(request(request_id="api-command"), Response(), tasks, None)
    assert entry.status == "pending" and entry.launch_pending
    assert all(not c.containers.creates for c in world.clients.values())
    assert len(tasks.tasks) == 1
    service.retry_deployment(entry.deployment_id)
    repeated = create_deployment_endpoint(request(request_id="api-command"), Response(), BackgroundTasks(), None)
    assert repeated.deployment_id == entry.deployment_id and repeated.status == "running"


def test_lost_container_create_ack_is_recovered_by_reserved_name_without_duplicate(world, monkeypatch):
    containers = world.clients["silo-1"].containers
    original = containers.create
    first = True
    def lost_ack(**kwargs):
        nonlocal first
        item = original(**kwargs)
        if first:
            first = False
            raise DockerException("fixture response lost after actual create")
        return item
    monkeypatch.setattr(containers, "create", lost_ack)
    failed = service.create_deployment(request())
    assert failed.status == "failed" and "silo-1" not in failed.container_map
    assert len(containers.items) == 1
    reset_repositories()
    recovered = service.retry_deployment(failed.deployment_id)
    assert recovered.status == "running" and recovered.verified_at
    assert len(containers.creates) == 1 and len(containers.items) == 1


def test_rollback_restores_previous_complete_configuration_and_verifies_before_marking(world):
    first = service.create_deployment(request(request_id="initial", env={"SETTING": "old"}, inference_port=8601))
    second = service.create_deployment(request(env={"SETTING": "new"}, inference_port=8602, target_node_ids=["silo-2"]))
    restored = service.rollback_deployment(second.deployment_id)
    assert restored.status == "running" and restored.verified_at
    assert restored.configuration.env == first.configuration.env
    assert restored.configuration.inference_port == 8601 and restored.target_node_ids == first.target_node_ids
    assert restored.configuration.request_id is None
    assert service.get_deployment(second.deployment_id).status == "rolled_back"
    assert all(result.verified_at for result in restored.target_results.values())


def test_rollback_failure_does_not_mark_success_and_retry_reuses_durable_restore_id(world):
    service.create_deployment(request(env={"SETTING": "old"}))
    current = service.create_deployment(request(env={"SETTING": "new"}))
    world.failed.add("silo-2")
    with pytest.raises(HTTPException) as rejected:
        service.rollback_deployment(current.deployment_id)
    assert rejected.value.status_code == 409
    pending = service.get_deployment(current.deployment_id)
    assert pending.status == "running" and pending.rollback_run_id
    restore_id = pending.rollback_run_id
    count = len(service.list_deployments())
    world.failed.clear()
    restored = service.rollback_deployment(current.deployment_id)
    assert restored.deployment_id == restore_id and restored.status == "running"
    assert len(service.list_deployments()) == count


def test_rollback_preserves_both_live_references_when_current_cleanup_is_unknown(world, monkeypatch):
    service.create_deployment(request())
    current = service.create_deployment(request())
    container = world.clients["silo-1"].containers.get(current.container_map["silo-1"])
    original = container.stop
    def fail(**_kwargs):
        raise DockerException("fixture cleanup unconfirmed")
    monkeypatch.setattr(container, "stop", fail)
    with pytest.raises(HTTPException) as rejected:
        service.rollback_deployment(current.deployment_id)
    assert rejected.value.status_code == 409
    after = service.get_deployment(current.deployment_id)
    restored = service.get_deployment(after.rollback_run_id)
    assert after.status == "failed" and after.cleanup_pending and after.container_map
    assert restored.status == "running" and restored.verified_at
    monkeypatch.setattr(container, "stop", original)
    assert service.rollback_deployment(current.deployment_id).deployment_id == restored.deployment_id
    assert service.get_deployment(current.deployment_id).status == "rolled_back"


@pytest.mark.parametrize("env", [{"MODEL_NAME": "spoof"}, {"1BAD": "value"}, {"OK": "bad\0value"}])
def test_invalid_env_rejected_before_reservation(env):
    with pytest.raises(ValidationError):
        request(env=env)


def test_duplicate_targets_and_non_batch_interval_rejected():
    for updates in ({"target_node_ids": ["silo-1", "silo-1"]}, {"interval_seconds": 10},
                    {"strategy": "batch", "interval_seconds": 0}):
        with pytest.raises(ValidationError):
            request(**updates)
