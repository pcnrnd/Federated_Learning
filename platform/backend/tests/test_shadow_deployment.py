"""기존 shadow API 계약. Docker/health는 대역, 실제 HTTP/가중치 비교는 test_serving_routes."""
import uuid

from docker.errors import DockerException
from fastapi import HTTPException
import pytest

from g5_helpers import IMAGE, IDENTITY, request, setup_world
from models.maintenance_schemas import ShadowDeploymentRequest
from models.packaging_schemas import ModelRegisterRequest
from services import deployment_runtime, deployment_service as deploy, model_registry, shadow_deployment_service as shadows


@pytest.fixture
def world(tmp_path, monkeypatch):
    value = setup_world(tmp_path, monkeypatch)
    model_registry.register_model(ModelRegisterRequest(name=IDENTITY["model"], version="1.1.0", framework="pytorch",
        weights_path=value.model.weights_path))
    monkeypatch.setattr(deployment_runtime, "pinned_package", lambda model, _request: (IMAGE, {**IDENTITY, "version": model.version}))
    return value


def create(primary, **updates):
    return shadows.create_shadow(ShadowDeploymentRequest(primary_deployment_id=primary.deployment_id,
        shadow_version="1.1.0", **updates))


def test_create_shadow_requires_running_verified_primary(world):
    primary = deploy.create_deployment(request())
    deploy.stop_deployment(primary.deployment_id)
    with pytest.raises(HTTPException) as rejected:
        create(primary)
    assert rejected.value.status_code == 409


def test_shadow_second_execution_and_request_retry_have_stable_route_and_child_identity(world):
    primary = deploy.create_deployment(request())
    identity = uuid.uuid4().hex
    first = create(primary, traffic_mirror_pct=20, request_id=identity)
    repeated = create(primary, traffic_mirror_pct=20, request_id=identity)
    assert first.status == "active" and first.shadow_deployment_id != primary.deployment_id
    assert repeated.shadow_id == first.shadow_id and repeated.shadow_deployment_id == first.shadow_deployment_id
    assert first.route_id and first.traffic_mirror_pct == 20
    with pytest.raises(HTTPException):
        create(primary, traffic_mirror_pct=30, request_id=identity)


def test_old_promote_without_real_comparison_evidence_is_rejected_and_primary_kept(world):
    primary = deploy.create_deployment(request())
    shadow = create(primary)
    with pytest.raises(HTTPException) as rejected:
        shadows.promote_shadow(shadow.shadow_id)
    assert rejected.value.status_code == 409
    assert deploy.get_deployment(primary.deployment_id).status == "running"


def test_abort_detaches_route_then_cleans_shadow_and_keeps_primary(world):
    primary = deploy.create_deployment(request())
    shadow = create(primary)
    aborted = shadows.abort_shadow(shadow.shadow_id)
    assert aborted.status == "aborted" and not aborted.cleanup_pending
    assert deploy.get_deployment(shadow.shadow_deployment_id).status == "stopped"
    assert deploy.get_deployment(primary.deployment_id).status == "running"
    assert shadows.abort_shadow(shadow.shadow_id).status == "aborted"


def test_abort_cleanup_failure_is_truthful_and_retry_recovers_same_child(world, monkeypatch):
    primary = deploy.create_deployment(request())
    shadow = create(primary)
    child = deploy.get_deployment(shadow.shadow_deployment_id)
    container = world.clients["silo-1"].containers.get(child.container_map["silo-1"])
    original = container.stop
    def fail(**_kw): raise DockerException("fixture cleanup failure")
    monkeypatch.setattr(container, "stop", fail)
    aborted = shadows.abort_shadow(shadow.shadow_id)
    assert aborted.status == "failed" and aborted.cleanup_pending
    with pytest.raises(HTTPException):
        model_registry.archive_model(IDENTITY["model"], "1.1.0")
    monkeypatch.setattr(container, "stop", original)
    assert shadows.abort_shadow(shadow.shadow_id).status == "aborted"
    assert deploy.get_deployment(primary.deployment_id).status == "running"
