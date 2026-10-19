"""G4-F2/F4: 실제 Docker 경계 대역, 영속 참조/재시작/예약 경합."""
import importlib
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from docker.errors import DockerException, NotFound
from fastapi import HTTPException

from g4_helpers import completed_live_result
from models.packaging_schemas import DeploymentEntry, DeploymentRequest, DeploymentTargetResult
from services import deployment_runtime, deployment_service as deploy, model_registry as registry, training_model_service as registration
from storage.factory import reset_repositories


@pytest.fixture(params=["yaml", "sqlite"])
def world(tmp_path, monkeypatch, request):
    monkeypatch.setenv("FED_STORAGE", request.param)
    reset_repositories()
    result = completed_live_result(tmp_path)
    entry = registration.register_completed_result(result.round_id)
    monkeypatch.setattr(deploy, "refresh_docker_hosts", lambda: None)
    monkeypatch.setattr(deploy, "get_docker_hosts", lambda: {"silo-1": {}, "silo-2": {}})
    # 라이프사이클/잠금 경계 시험이며 실제 image/HTTP 확인은 G5 runtime 회귀가 담당한다.
    monkeypatch.setattr(deployment_runtime, "pinned_package", lambda *_args: ("sha256:fixture", {}))
    monkeypatch.setattr(deployment_runtime, "probe_inputs", lambda *_args: [[1, 2, 3]])
    monkeypatch.setattr(deployment_runtime, "ensure_image", lambda *_args: None)
    monkeypatch.setattr(deployment_runtime, "verify_target", lambda _c, container, *_args, **_kw:
        DeploymentTargetResult(status="running", container_id=container.id, image_id="sha256:fixture",
            verified_at=deploy._now_iso()))
    return entry


def request_for(entry):
    return DeploymentRequest(model_name=entry.name, version=entry.version, strategy="realtime",
        target_node_ids=["silo-1", "silo-2"])


def stored(entry, **extra):
    values = dict(deployment_id="owned", model_name=entry.name, version=entry.version, image_tag="test:1",
        strategy="realtime", target_node_ids=["silo-1", "silo-2"], container_map={"silo-1": "c1", "silo-2": "c2"},
        status="running", created_at="2026-10-19T00:00:00Z")
    values.update(extra)
    result = DeploymentEntry(**values)
    deploy._save(result)
    return result


@pytest.mark.parametrize("boundary", ["stop", "remove"])
def test_partial_cleanup_is_truthful_and_keeps_reference_after_reload_until_confirmed_absent(world, monkeypatch, boundary):
    stored(world)
    first, second = MagicMock(), MagicMock()
    getattr(second, boundary).side_effect = DockerException("injected cleanup failure")
    clients = {"silo-1": SimpleNamespace(containers=SimpleNamespace(get=lambda _id: first)),
        "silo-2": SimpleNamespace(containers=SimpleNamespace(get=lambda _id: second))}
    monkeypatch.setattr(deploy, "get_docker_client", clients.__getitem__)
    after = deploy.stop_deployment("owned")
    assert after.status == "failed" and after.cleanup_pending
    assert after.container_map == {"silo-2": "c2"}
    assert after.cleanup_results["silo-1"] == "removed_or_confirmed_absent"
    assert after.cleanup_results["silo-2"].startswith("unknown:")
    first.remove.assert_called_once()
    importlib.reload(deploy)
    for action in (registry.archive_model, registry.delete_model):
        with pytest.raises(HTTPException) as blocked:
            action(world.name, world.version)
        assert blocked.value.status_code == 409
    def absent(_identity):
        raise NotFound("confirmed absent after restart")
    monkeypatch.setattr(deploy, "refresh_docker_hosts", lambda: None)
    monkeypatch.setattr(deploy, "get_docker_client", lambda _node: SimpleNamespace(containers=SimpleNamespace(get=absent)))
    after = deploy.stop_deployment("owned")
    assert after.status == "stopped" and not after.cleanup_pending and after.container_map == {}
    weights = registry.get_ridge_artifact(world).weights_path
    assert registry.archive_model(world.name, world.version).status == "archived"
    registry.delete_model(world.name, world.version)
    assert weights.is_file()
    assert registration.reconcile_completed_results() == []
    assert registration.list_registrations()[0]["status"] == "deleted"


def test_legacy_stopped_with_unverified_container_is_still_a_reference(world):
    stored(world, status="stopped")
    for action in (registry.archive_model, registry.delete_model):
        with pytest.raises(HTTPException) as blocked:
            action(world.name, world.version)
        assert blocked.value.status_code == 409


def test_user_labels_cannot_replace_durable_deployment_discovery_identity():
    from services.deployment_strategies import _common_labels
    request = DeploymentRequest(model_name="m", version="1.0.0", strategy="realtime", target_node_ids=["silo-1"],
        labels={"fed.deployment_id": "other", "fed.model": "other", "custom": "kept"})
    labels = _common_labels(request, "durable-reservation", "realtime")
    assert labels["fed.deployment_id"] == "durable-reservation"
    assert labels["fed.model"] == "m" and labels["custom"] == "kept"


@pytest.mark.parametrize("after_write", [False, True])
def test_pending_save_failure_never_launches_and_durable_unknown_survives_restart(world, monkeypatch, after_write):
    original = deploy.save_deployments
    def fail(values):
        if after_write:
            original(values)
        raise OSError("injected pending save boundary")
    monkeypatch.setattr(deploy, "save_deployments", fail)
    docker = MagicMock()
    monkeypatch.setattr(deploy, "get_docker_client", docker)
    with pytest.raises(OSError):
        deploy.create_deployment(request_for(world))
    docker.assert_not_called()
    importlib.reload(deploy)
    if not after_write:
        assert deploy.list_deployments() == []
        assert registry.archive_model(world.name, world.version).status == "archived"
        return
    saved = deploy.list_deployments()[0]
    assert saved.status == "pending" and saved.launch_pending and saved.container_map == {}
    assert deploy.reconcile_deployment(saved.deployment_id).current_status == "pending"
    for action in (registry.archive_model, registry.delete_model):
        with pytest.raises(HTTPException):
            action(world.name, world.version)
    monkeypatch.setattr(deploy, "refresh_docker_hosts", lambda: None)
    monkeypatch.setattr(deploy, "get_docker_client", lambda _node: SimpleNamespace(containers=SimpleNamespace(list=lambda **_kw: [])))
    cleared = deploy.stop_deployment(saved.deployment_id)
    assert not cleared.launch_pending and cleared.status == "stopped"
    assert registry.archive_model(world.name, world.version).status == "archived"


@pytest.mark.parametrize("action", ["archive_model", "delete_model"])
def test_lifecycle_wins_before_pending_reservation_and_no_docker_runs(world, monkeypatch, action):
    checked, resume = threading.Event(), threading.Event()
    def park():
        checked.set()
        assert resume.wait(5)
    monkeypatch.setattr(deploy, "refresh_docker_hosts", park)
    docker = MagicMock()
    monkeypatch.setattr(deploy, "get_docker_client", docker)
    with ThreadPoolExecutor(max_workers=1) as pool:
        attempt = pool.submit(deploy.create_deployment, request_for(world))
        try:
            assert checked.wait(5)
            getattr(registry, action)(world.name, world.version)
        finally:
            resume.set()
        with pytest.raises(HTTPException) as rejected:
            attempt.result(timeout=5)
    assert rejected.value.status_code in (404, 409)
    assert deploy.list_deployments() == []
    docker.assert_not_called()


def test_durable_pending_wins_while_docker_waits_without_global_registry_lock(world, monkeypatch):
    entered, resume = threading.Event(), threading.Event()
    class Strategy:
        def deploy_to_node(self, context, _request, identity):
            saved = deploy.get_deployment(identity)
            assert saved.launch_pending and saved.status == "pending"
            entered.set()
            assert resume.wait(5)
            return SimpleNamespace(node_id=context.node_id, container_id="container-" + context.node_id)
    monkeypatch.setattr(deploy, "get_strategy", lambda _strategy: Strategy())
    monkeypatch.setattr(deploy, "get_docker_client", lambda node: SimpleNamespace(
        containers=SimpleNamespace(get=lambda _identity: SimpleNamespace(id="container-"+node)), close=lambda: None))
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempt = pool.submit(deploy.create_deployment, request_for(world))
        try:
            assert entered.wait(5)
            for action in (registry.archive_model, registry.delete_model):
                # 작업 스레드가 Docker에서 대기해도 전역 registry lock을 점유하지 않는다.
                check = pool.submit(action, world.name, world.version)
                with pytest.raises(HTTPException) as blocked:
                    check.result(timeout=1)
                assert blocked.value.status_code == 409
        finally:
            resume.set()
        result = attempt.result(timeout=5)
    assert result.status == "running" and not result.launch_pending
    assert registry.get_model(world.name, world.version).status == "active"


def test_archived_direct_request_rejected_before_docker_metadata_and_unknown_launch_is_discovered(world, monkeypatch):
    registry.archive_model(world.name, world.version)
    refresh = MagicMock()
    monkeypatch.setattr(deploy, "refresh_docker_hosts", refresh)
    with pytest.raises(HTTPException) as blocked:
        deploy.create_deployment(request_for(world))
    assert blocked.value.status_code == 409
    refresh.assert_not_called()
    entry = stored(world, container_map={}, status="failed", launch_pending=True)
    orphan = MagicMock()
    orphan.id, orphan.labels = "unreported-container", {"fed.deployment_id": entry.deployment_id}
    def client_for(node):
        return SimpleNamespace(containers=SimpleNamespace(list=lambda **_kw: [orphan] if node == "silo-1" else []))
    monkeypatch.setattr(deploy, "get_docker_client", client_for)
    result = deploy.stop_deployment(entry.deployment_id)
    assert result.status == "stopped" and not result.launch_pending and not result.cleanup_pending
    orphan.remove.assert_called_once()
