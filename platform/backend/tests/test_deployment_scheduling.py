"""G5-A persisted occurrence: YAML/SQLite, 실제 전략 + Docker/health 경계 대역."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from g5_helpers import request, setup_world
from services import deployment_scheduling as scheduling, deployment_service as service
from storage.factory import reset_repositories


@pytest.fixture(params=["yaml", "sqlite"])
def world(tmp_path, monkeypatch, request):
    monkeypatch.setenv("FED_STORAGE", request.param)
    reset_repositories()
    return setup_world(tmp_path, monkeypatch)


def schedule():
    return service.create_deployment(request(strategy="batch", interval_seconds=30, request_id="periodic-command"))


def children(parent):
    return [entry for entry in service.list_deployments() if entry.schedule_parent_id == parent.deployment_id]


def test_first_due_next_scheduled_time_and_no_duplicate_concurrent_ticks(world):
    parent = schedule()
    due = datetime.fromisoformat(parent.next_due_at)
    assert due == datetime.fromisoformat(parent.created_at) + timedelta(seconds=30)
    assert parent.status == "pending" and parent.is_schedule and not parent.launch_pending
    assert scheduling.tick(due-timedelta(microseconds=1)) == []
    assert all(not c.containers.creates for c in world.clients.values())
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _i: scheduling.tick(due), range(2)))
    first = service.get_deployment(parent.deployment_id)
    assert first.occurrence == 1 and len(children(parent)) == 1
    assert datetime.fromisoformat(first.next_due_at) == due+timedelta(seconds=30)
    assert all(len(c.containers.creates) == 1 for c in world.clients.values())
    assert first.configuration.env == {"APP_SETTING": "preserved=value"}
    scheduling.tick(due+timedelta(seconds=35))
    second = service.get_deployment(parent.deployment_id)
    assert second.occurrence == 2 and len(children(parent)) == 2
    assert datetime.fromisoformat(second.next_due_at) == due+timedelta(seconds=60)
    assert service.get_deployment(first.current_run_id).status == "stopped"
    assert all(len(c.containers.items) == 1 for c in world.clients.values())


@pytest.mark.parametrize("boundary", ["intent-before", "intent-after", "child-after", "final-before", "final-after"])
def test_same_process_retry_and_repository_reload_do_not_duplicate_or_lose_occurrence(world, monkeypatch, boundary):
    parent = schedule()
    due = datetime.fromisoformat(parent.next_due_at)
    original = service._save
    injected = False
    def save(entry):
        nonlocal injected
        parent_entry = entry.deployment_id == parent.deployment_id
        point = (parent_entry and entry.opening_run_id and entry.occurrence == 0 and boundary.startswith("intent"))
        point = point or (entry.schedule_parent_id == parent.deployment_id and boundary == "child-after")
        point = point or (parent_entry and entry.occurrence == 1 and boundary.startswith("final"))
        if point and not injected:
            injected = True
            if boundary.endswith("after"):
                original(entry)
            raise OSError("injected durable occurrence boundary")
        original(entry)
    monkeypatch.setattr(service, "_save", save)
    with pytest.raises(OSError):
        scheduling.tick(due)
    assert injected
    if boundary.startswith("intent"):
        assert children(parent) == [] and all(not c.containers.creates for c in world.clients.values())
    # 즉시 같은 프로세스 retry: 저장 안 된 in-memory intent로 child를 열면 안 된다.
    scheduling.tick(due)
    reset_repositories()
    scheduling.tick(due)
    after = service.get_deployment(parent.deployment_id)
    assert after.occurrence == 1 and not after.opening_run_id and len(children(parent)) == 1
    assert datetime.fromisoformat(after.next_due_at) == due+timedelta(seconds=30)
    assert all(len(c.containers.creates) == 1 for c in world.clients.values())
    assert all(item.status == "running" for c in world.clients.values() for item in c.containers.items.values())


def test_failed_occurrence_pauses_schedule_and_retry_uses_same_child_and_target_settings(world):
    parent = schedule()
    due = datetime.fromisoformat(parent.next_due_at)
    world.failed.add("silo-1")
    scheduling.tick(due)
    failed = service.get_deployment(parent.deployment_id)
    identity = failed.opening_run_id
    assert failed.status == "failed" and not failed.schedule_active and identity
    scheduling.tick(due+timedelta(seconds=90))
    assert len(children(parent)) == 1 and service.get_deployment(parent.deployment_id).occurrence == 0
    reset_repositories()
    world.failed.clear()
    resumed = service.retry_deployment(parent.deployment_id)
    assert resumed.occurrence == 1 and resumed.current_run_id == identity and resumed.schedule_active
    assert all(len(c.containers.creates) == 1 for c in world.clients.values())


def test_stop_disables_future_schedule_and_cleans_current_child(world):
    parent = schedule()
    due = datetime.fromisoformat(parent.next_due_at)
    scheduling.tick(due)
    stopped = service.stop_deployment(parent.deployment_id)
    assert stopped.status == "stopped" and not stopped.schedule_active and not stopped.cleanup_pending
    scheduling.tick(due+timedelta(hours=1))
    assert len(children(parent)) == 1
    assert all(not client.containers.items for client in world.clients.values())


def test_pending_immediate_deployment_recovers_after_restart_without_new_execution_identity(world):
    pending = service.create_deployment(request(request_id="pending-before-restart"), defer=True)
    reset_repositories()
    scheduling.tick()
    after = service.get_deployment(pending.deployment_id)
    assert after.status == "running" and after.verified_at
    scheduling.tick()
    assert len(service.list_deployments()) == 1
    assert all(len(c.containers.creates) == 1 for c in world.clients.values())
