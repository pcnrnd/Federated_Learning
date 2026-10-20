"""G5-B-F1/F2: 실제 저장소 경계와 동시성, Docker 대역. 운영 Docker 실증이 아니다."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading
import uuid

from docker.errors import DockerException
from fastapi import HTTPException
import pytest

from g5_helpers import IMAGE, IDENTITY, request as deploy_request, setup_world
from models.maintenance_schemas import ShadowDeploymentRequest
from models.packaging_schemas import ModelRegisterRequest
from services import deployment_runtime, deployment_scheduling, deployment_service as deploy
from services import model_registry, serving_routes as routes, serving_store as store, shadow_deployment_service as shadows
from storage.factory import reset_repositories


@pytest.fixture(params=["yaml", "sqlite"])
def state(tmp_path, monkeypatch, request):
    monkeypatch.setenv("FED_STORAGE", request.param)
    reset_repositories()
    world = setup_world(tmp_path, monkeypatch)
    model_registry.register_model(ModelRegisterRequest(name=IDENTITY["model"], version="1.1.0", framework="pytorch",
        weights_path=world.model.weights_path))
    monkeypatch.setattr(deployment_runtime, "pinned_package",
        lambda model, _request: (IMAGE, {**IDENTITY, "version": model.version}))
    primary = deploy.create_deployment(deploy_request())
    route = routes.ensure_route(primary.deployment_id)
    command = ShadowDeploymentRequest(primary_deployment_id=primary.deployment_id, route_id=route.route_id,
        shadow_version="1.1.0", request_id=uuid.uuid4().hex)
    return world, primary, route, command


def child_for(entry):
    found = [child for child in deploy.list_deployments() if child.configuration
        and child.configuration.request_id == entry.deployment_request.request_id]
    assert len(found) == 1
    return found[0]


def lose_child_link(monkeypatch, command, *, after):
    original, fired = shadows._save, False
    def save(entry):
        nonlocal fired
        if entry.shadow_deployment_id and not fired:
            fired = True
            if after:
                original(entry)
            raise OSError("injected child-link write/response loss")
        original(entry)
    monkeypatch.setattr(shadows, "_save", save)
    with pytest.raises(OSError):
        shadows.create_shadow(command)
    assert fired
    reset_repositories()
    return shadows.list_shadows()[0]


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_F1_abort_recovers_unlinked_pending_child_by_request_id_without_create(state, monkeypatch, after, cleanup_failure):
    world, primary, _route, command = state
    entry = lose_child_link(monkeypatch, command, after=after)
    child = child_for(entry)
    assert child.status == "pending"
    assert bool(entry.shadow_deployment_id) == after
    creates = sum(len(client.containers.creates) for client in world.clients.values())
    def forbidden(*_args, **_kwargs):
        raise AssertionError("abort must not create a deployment")
    monkeypatch.setattr(deploy, "create_deployment", forbidden)
    containers = world.clients["silo-1"].containers
    original = containers.list
    if cleanup_failure:
        def fail(**kwargs):
            if kwargs.get("filters", {}).get("label") == "fed.deployment_id="+child.deployment_id:
                raise DockerException("injected unknown pending-child inventory")
            return original(**kwargs)
        monkeypatch.setattr(containers, "list", fail)
        blocked = shadows.abort_shadow(entry.shadow_id)
        assert blocked.status == "failed" and blocked.cleanup_pending
        reset_repositories()
        monkeypatch.setattr(containers, "list", original)
    aborted = shadows.abort_shadow(entry.shadow_id)
    assert aborted.status == "aborted" and not aborted.cleanup_pending
    assert deploy.get_deployment(child.deployment_id).status == "stopped"
    reset_repositories()
    deployment_scheduling.tick(datetime.now(timezone.utc))
    assert shadows.abort_shadow(entry.shadow_id).status == "aborted"
    assert sum(len(client.containers.creates) for client in world.clients.values()) == creates
    assert deploy.get_deployment(primary.deployment_id).status == "running"
    assert len([entry for entry in deploy.list_deployments() if entry.configuration
        and entry.configuration.request_id == child.configuration.request_id]) == 1


def test_F1_close_recovers_reserved_unlinked_child_before_any_pending_retry(state, monkeypatch):
    world, _primary, route, command = state
    entry = lose_child_link(monkeypatch, command, after=False)
    child = child_for(entry)
    closed = routes.close(route.route_id)
    assert closed.status == "closed" and not closed.cleanup_pending
    assert deploy.get_deployment(child.deployment_id).status == "stopped"
    deployment_scheduling.tick(datetime.now(timezone.utc))
    assert all(not client.containers.items for client in world.clients.values())


def test_F2_distinct_commands_compete_before_child_side_effects_and_same_command_retries(state, monkeypatch):
    world, _primary, route, command = state
    original = routes.attach_shadow
    entered, resume = threading.Event(), threading.Event()
    def attach(*args, **kwargs):
        entered.set()
        assert resume.wait(3)
        return original(*args, **kwargs)
    monkeypatch.setattr(routes, "attach_shadow", attach)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(shadows.create_shadow, command)
        try:
            assert entered.wait(3)
            assert routes.get_route(route.route_id).shadow_id
            with pytest.raises(HTTPException) as rejected:
                shadows.create_shadow(command.model_copy(update={"request_id": uuid.uuid4().hex}))
            assert rejected.value.status_code == 409
            assert len(shadows.list_shadows()) == 1
            assert len([entry for entry in deploy.list_deployments()
                if entry.configuration and (entry.configuration.request_id or "").startswith("shadow-")]) == 1
        finally:
            resume.set()
        active = first.result(timeout=4)
    count = sum(len(client.containers.creates) for client in world.clients.values())
    repeated = shadows.create_shadow(command)
    assert repeated.shadow_id == active.shadow_id and repeated.shadow_deployment_id == active.shadow_deployment_id
    assert sum(len(client.containers.creates) for client in world.clients.values()) == count


@pytest.mark.parametrize("after", [False, True])
def test_F2_slot_write_failure_never_authorizes_child_and_reload_reuses_same_intent(state, monkeypatch, after):
    _world, _primary, route, command = state
    original, fired = store.save, False
    def save(data):
        nonlocal fired
        if data["routes"][route.route_id].get("shadow_id") and not fired:
            fired = True
            if after:
                original(data)
            raise OSError("injected route reservation write/response loss")
        original(data)
    monkeypatch.setattr(store, "save", save)
    with pytest.raises(OSError):
        shadows.create_shadow(command)
    intent = shadows.list_shadows()[0]
    assert not any(entry.configuration and (entry.configuration.request_id or "").startswith("shadow-")
        for entry in deploy.list_deployments())
    reset_repositories()
    active = shadows.create_shadow(command)
    assert active.shadow_id == intent.shadow_id and active.status == "active"
    assert routes.get_route(route.route_id).shadow_id == intent.shadow_id
    assert child_for(active).deployment_id == active.shadow_deployment_id


@pytest.mark.parametrize("status", ["promoted", "rolled_back", "closed"])
def test_F2_unsupported_route_state_rejected_before_intent_or_child_creation(state, status):
    world, _primary, route, command = state
    data = store.read()
    data["routes"][route.route_id].update(status=status, shadow_id="old-comparison")
    store.save(data)
    before = len(deploy.list_deployments())
    creates = sum(len(client.containers.creates) for client in world.clients.values())
    with pytest.raises(HTTPException) as rejected:
        shadows.create_shadow(command)
    assert rejected.value.status_code == 409
    assert shadows.list_shadows() == [] and len(deploy.list_deployments()) == before
    assert sum(len(client.containers.creates) for client in world.clients.values()) == creates


def test_F2_unpersisted_slot_loser_abort_cannot_detach_the_winning_command(state, monkeypatch):
    _world, _primary, route, command = state
    original, fired = store.save, False
    def save(data):
        nonlocal fired
        if data["routes"][route.route_id].get("shadow_id") and not fired:
            fired = True
            raise OSError("reservation was not persisted")
        original(data)
    monkeypatch.setattr(store, "save", save)
    with pytest.raises(OSError):
        shadows.create_shadow(command)
    loser = shadows.list_shadows()[0]
    reset_repositories()
    winner = shadows.create_shadow(command.model_copy(update={"request_id": uuid.uuid4().hex}))
    with pytest.raises(HTTPException):
        shadows.retry_shadow(loser.shadow_id)
    assert shadows.abort_shadow(loser.shadow_id).status == "aborted"
    current = routes.get_route(route.route_id)
    assert current.shadow_id == winner.shadow_id and current.shadow_deployment_id == winner.shadow_deployment_id
    assert deploy.get_deployment(winner.shadow_deployment_id).status == "running"
    assert len([entry for entry in deploy.list_deployments() if entry.configuration
        and (entry.configuration.request_id or "").startswith("shadow-")]) == 1
