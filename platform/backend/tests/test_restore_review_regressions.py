"""고정 ee0 독립 검토 G5-A-F1/F2/F3 결합 경계. Docker 대역/실제 ridge HTTP를 구분한다."""
from datetime import datetime, timedelta
import uuid

from fastapi import HTTPException
import pytest
from docker.errors import DockerException

from g5_helpers import request as deploy_request, setup_world
from models.packaging_schemas import ModelRestoreRequest
from services import deployment_runtime, deployment_scheduling, deployment_service as deploy, model_registry, selected_model_restore
from serving_helpers import setup
from storage.factory import reset_repositories
import test_ridge_artifacts as ridge_fixtures

# pytest가 수집할 동일 fixture 객체를 원래 이름으로 재노출한다.
completed_result = ridge_fixtures.completed_result


@pytest.fixture(params=["yaml", "sqlite"])
def actual(tmp_path, monkeypatch, request, completed_result):
    monkeypatch.setenv("FED_STORAGE", request.param)
    reset_repositories()
    value = setup(tmp_path, monkeypatch, completed_result, versions=3)
    original = deployment_runtime.verify_target
    def verify(*args, **kwargs):
        kwargs["timeout"] = .25
        return original(*args, **kwargs)
    monkeypatch.setattr(deployment_runtime, "verify_target", verify)
    current = deploy.get_deployment("current")
    deploy._save(current.model_copy(update={"previous_deployment_id": "primary"}))
    yield value
    value.resume.set()
    for http, thread in value.servers:
        http.shutdown()
        http.server_close()
        thread.join(3)
        assert not thread.is_alive()


def prediction(entry):
    return deployment_runtime._json_request(entry.target_results["silo-1"].endpoint+"/predict", {"inputs": [[1, 2, 3]]})


def test_F1_selected_archived_V2_restores_V2_not_its_previous_V1_and_request_retry_reuses_identity(actual):
    deploy.stop_deployment("shadow")
    assert model_registry.archive_model("model", "1.0.1").status == "archived"
    request = ModelRestoreRequest(name="model", version="1.0.1", request_id=uuid.uuid4().hex)
    restored = selected_model_restore.restore(request)
    assert restored.version == "1.0.1" and restored.configuration.version == "1.0.1"
    assert model_registry.get_model("model", "1.0.1").status == "active"
    assert prediction(restored)["predictions"] == [15.0]
    reset_repositories()
    repeated = selected_model_restore.restore(request)
    assert repeated.deployment_id == restored.deployment_id


def test_F1_timeline_V3_previous_rollback_still_restores_V1(actual):
    restored = deploy.rollback_deployment("current")
    assert restored.version == "1.0.0" and prediction(restored)["predictions"] == [13.0]


def test_F1_failed_selected_restore_does_not_replace_current_or_claim_completion(actual):
    deploy.stop_deployment("shadow")
    model_registry.archive_model("model", "1.0.1")
    actual.faults["1.0.1"]["predict"] = True
    request = ModelRestoreRequest(name="model", version="1.0.1", request_id=uuid.uuid4().hex)
    with pytest.raises(HTTPException):
        selected_model_restore.restore(request)
    assert deploy.get_deployment("current").status == "running"
    assert prediction(deploy.get_deployment("current"))["predictions"] == [17.0]
    assert any(entry.version == "1.0.1" and entry.status == "failed" for entry in deploy.list_deployments())


def test_F1_absent_verified_history_rejects_without_switching_other_version(actual):
    with pytest.raises(HTTPException) as rejected:
        selected_model_restore.restore(ModelRestoreRequest(name="model", version="9.9.9", request_id=uuid.uuid4().hex))
    assert rejected.value.status_code == 409
    assert deploy.get_deployment("current").status == "running"


def test_F3_failed_current_keeps_previous_version_reference_after_reload_then_releases_after_cleanup(actual):
    deploy.stop_deployment("primary")
    actual.faults["1.0.2"]["predict"] = True
    assert deploy.reconcile_deployment("current").current_status == "failed"
    reset_repositories()
    for action in (model_registry.archive_model, model_registry.delete_model):
        with pytest.raises(HTTPException) as blocked:
            action("model", "1.0.0")
        assert blocked.value.status_code == 409
    restored = deploy.rollback_deployment("current")
    assert restored.version == "1.0.0" and prediction(restored)["predictions"] == [13.0]
    deploy.stop_deployment(restored.deployment_id)
    assert model_registry.archive_model("model", "1.0.0").status == "archived"


@pytest.mark.parametrize("backend", ["yaml", "sqlite"])
@pytest.mark.parametrize("boundary", ["none", "parent-link-before", "parent-link-after", "cleanup"])
def test_F2_batch_rollback_parent_owns_restored_run_across_link_failure_reload_due_and_stop(tmp_path, monkeypatch, backend, boundary):
    monkeypatch.setenv("FED_STORAGE", backend)
    reset_repositories()
    world = setup_world(tmp_path, monkeypatch)
    parent = deploy.create_deployment(deploy_request(strategy="batch", interval_seconds=30))
    due = datetime.fromisoformat(parent.next_due_at)
    deployment_scheduling.tick(due)
    deployment_scheduling.tick(due+timedelta(seconds=30))
    child = deploy.get_deployment(parent.deployment_id).current_run_id
    original, fired = deploy._save, False
    def save(entry):
        nonlocal fired
        if (boundary.startswith("parent-link") and not fired and entry.deployment_id == parent.deployment_id
                and entry.current_run_id != child and not entry.schedule_active):
            fired = True
            if boundary.endswith("after"):
                original(entry)
            raise OSError("injected parent restore link")
        original(entry)
    monkeypatch.setattr(deploy, "_save", save)
    if boundary in ("none", "cleanup"):
        restored = deploy.rollback_deployment(child)
    else:
        with pytest.raises(OSError):
            deploy.rollback_deployment(child)
        restored = deploy.get_deployment(deploy.get_deployment(child).rollback_run_id)
        reset_repositories()
        deployment_scheduling.tick(due+timedelta(hours=1))
        assert deploy.rollback_deployment(child).deployment_id == restored.deployment_id
    current = deploy.get_deployment(parent.deployment_id)
    assert current.current_run_id == restored.deployment_id and not current.schedule_active
    deployment_scheduling.tick(due+timedelta(hours=2))
    assert deploy.get_deployment(parent.deployment_id).current_run_id == restored.deployment_id
    if boundary == "cleanup":
        container = world.clients["silo-1"].containers.get(restored.container_map["silo-1"])
        stop = container.stop
        def fail(**_kwargs): raise DockerException("fixture cleanup failure")
        monkeypatch.setattr(container, "stop", fail)
        failed = deploy.stop_deployment(parent.deployment_id)
        assert failed.status == "failed" and failed.cleanup_pending
        monkeypatch.setattr(container, "stop", stop)
    stopped = deploy.stop_deployment(parent.deployment_id)
    assert stopped.status == "stopped" and not stopped.cleanup_pending
    assert all(not client.containers.items for client in world.clients.values())


@pytest.mark.parametrize("backend", ["yaml", "sqlite"])
@pytest.mark.parametrize("boundary", ["none", "intent-before", "intent-after", "restore-before", "restore-after",
    "link-before", "link-after", "cleanup", "legacy-no-parent"])
@pytest.mark.parametrize("ticks", [0, 1])
def test_F2_repeated_restore_chain_remains_schedule_owned_and_stop_cleans_transitively(tmp_path, monkeypatch, backend, boundary, ticks):
    monkeypatch.setenv("FED_STORAGE", backend)
    reset_repositories()
    world = setup_world(tmp_path, monkeypatch)
    parent = deploy.create_deployment(deploy_request(strategy="batch", interval_seconds=30))
    due = datetime.fromisoformat(parent.next_due_at)
    deployment_scheduling.tick(due)
    deployment_scheduling.tick(due+timedelta(seconds=30))
    previous = deploy.get_deployment(parent.deployment_id).current_run_id
    chain = [previous]
    original, fired = deploy._save, False
    def save(entry):
        nonlocal fired
        intent = entry.deployment_id == chain[-1] and entry.rollback_run_id and entry.status == "running"
        restore = (entry.deployment_id not in chain and entry.deployment_id != parent.deployment_id
            and entry.schedule_parent_id == parent.deployment_id and entry.status == "pending")
        link = entry.deployment_id == parent.deployment_id and entry.current_run_id != chain[-1]
        selected = ((boundary.startswith("intent-") and intent) or (boundary.startswith("restore-") and restore)
            or (boundary.startswith("link-") and link))
        if len(chain) == 3 and not fired and selected:
            fired = True
            if boundary.endswith("after"):
                original(entry)
            raise OSError("injected third restore parent adoption")
        original(entry)
    monkeypatch.setattr(deploy, "_save", save)
    for _index in range(3):
        before = chain[-1]
        if boundary == "legacy-no-parent" and len(chain) > 1:
            entry = deploy.get_deployment(before)
            original(entry.model_copy(update={"schedule_parent_id": None}))
        try:
            restored = deploy.rollback_deployment(before)
        except OSError:
            assert fired
            reset_repositories()
            saved_id = deploy.get_deployment(before).rollback_run_id
            if boundary.startswith("link-"):
                restored = deploy.get_deployment(saved_id)
            else:
                restored = deploy.rollback_deployment(before)
                if saved_id:
                    assert restored.deployment_id == saved_id
        assert restored.schedule_parent_id == parent.deployment_id
        chain.append(restored.deployment_id)
    assert len(set(chain)) == 4
    reset_repositories()
    if ticks:
        deployment_scheduling.tick(due+timedelta(hours=1))
    if boundary == "link-before" and ticks == 0:
        # parent 연결 유실은 tick/재시도 없이 즉시 stop해도 마지막 실제 실행을 회수해야 한다.
        assert deploy.get_deployment(parent.deployment_id).current_run_id == chain[-2]
    else:
        repeated = deploy.rollback_deployment(chain[-2])
        assert repeated.deployment_id == chain[-1]
        assert deploy.get_deployment(parent.deployment_id).current_run_id == chain[-1]
    assert deployment_scheduling.owned_run_ids(deploy.get_deployment(parent.deployment_id)).issuperset(chain)
    leaf = deploy.get_deployment(chain[-1])
    container = world.clients["silo-1"].containers.get(leaf.container_map["silo-1"])
    stop = container.stop
    if boundary == "cleanup":
        def fail(**_kwargs):
            raise DockerException("injected last restored execution cleanup")
        monkeypatch.setattr(container, "stop", fail)
        failed = deploy.stop_deployment(parent.deployment_id)
        assert failed.status == "failed" and failed.cleanup_pending
        reset_repositories()
        monkeypatch.setattr(container, "stop", stop)
    stopped = deploy.stop_deployment(parent.deployment_id)
    assert stopped.status == "stopped" and not stopped.cleanup_pending
    assert all(not client.containers.items for client in world.clients.values())
    assert len({entry.deployment_id for entry in deploy.list_deployments() if entry.deployment_id in chain}) == 4


@pytest.mark.parametrize("backend", ["yaml", "sqlite"])
def test_F2_restore_cycle_is_not_reported_as_successful_parent_cleanup(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("FED_STORAGE", backend)
    reset_repositories()
    setup_world(tmp_path, monkeypatch)
    parent = deploy.create_deployment(deploy_request(strategy="batch", interval_seconds=30))
    deployment_scheduling.tick(datetime.fromisoformat(parent.next_due_at))
    child = deploy.get_deployment(parent.deployment_id).current_run_id
    entry = deploy.get_deployment(child)
    deploy._save(entry.model_copy(update={"rollback_run_id": child}))
    stopped = deploy.stop_deployment(parent.deployment_id)
    assert stopped.status == "failed" and stopped.cleanup_pending
