"""기존 shadow API를 실제 serving route/비교 gate와 연결한다."""
import uuid

from fastapi import HTTPException

from config.maintenance_manager import load_shadows, save_shadows
from models.maintenance_schemas import ShadowDeployment, ShadowDeploymentRequest
from services import deployment_service as deployments, serving_requests, serving_routes, serving_store
from services.model_registry import REGISTRY_LOCK, get_model


def _save(entry):
    with REGISTRY_LOCK:
        values = load_shadows()
        values[entry.shadow_id] = entry.model_dump()
        save_shadows(values)


def _overlay(entry):
    outcome = serving_store.read()["shadows"].get(entry.shadow_id)
    if outcome:
        entry = entry.model_copy(update={"status": outcome["status"], "cleanup_pending": outcome.get("cleanup_pending", False),
            "shadow_deployment_id": outcome.get("deployment_id") or entry.shadow_deployment_id})
    return entry


def list_shadows(status=None):
    with REGISTRY_LOCK:
        entries = [_overlay(ShadowDeployment(**value)) for value in load_shadows().values()]
    return sorted((entry for entry in entries if status is None or entry.status == status), key=lambda entry: entry.created_at, reverse=True)


def get_shadow(identity):
    with REGISTRY_LOCK:
        raw = load_shadows().get(identity)
        if raw is None:
            raise HTTPException(status_code=404, detail="shadow 배포가 없습니다")
        return _overlay(ShadowDeployment(**raw))


def create_shadow(request: ShadowDeploymentRequest):
    with REGISTRY_LOCK:
        identity = None
        if request.request_id:
            for entry in list_shadows():
                if entry.request_id == request.request_id:
                    if not entry.request_snapshot or entry.request_snapshot.model_dump() != request.model_dump():
                        raise HTTPException(status_code=409, detail="같은 shadow 요청 ID의 다른 설정입니다")
                    identity = entry.shadow_id
                    break
        if identity is None:
            primary = serving_requests.deployment(request.primary_deployment_id)
            model = get_model(primary.model_name, request.shadow_version)
            if model.status != "active" or primary.configuration is None:
                raise HTTPException(status_code=409, detail="활성 모델과 복구 가능한 primary 실행 설정이 필요합니다")
            route = serving_routes.get_route(request.route_id) if request.route_id else serving_routes.ensure_route(primary.deployment_id)
            if route.primary_deployment_id != primary.deployment_id or route.status == "closed" or route.shadow_deployment_id:
                raise HTTPException(status_code=409, detail="primary와 일치하는 비어 있는 비교 route가 필요합니다")
            identity = uuid.uuid4().hex
            deploy_request = primary.configuration.model_copy(deep=True, update={"version": request.shadow_version,
                "strategy": "edge" if primary.strategy == "edge" else "realtime", "interval_seconds": None,
                "request_id": "shadow-"+identity, "target_node_ids": request.target_node_ids or list(primary.target_node_ids),
                "image_tag": request.image_tag, "container_name_prefix": "shadow",
                "probe_inputs": request.probe_inputs if request.probe_inputs is not None else primary.configuration.probe_inputs,
                "labels": {"fed.role": "shadow", "fed.primary_deployment": primary.deployment_id}})
            entry = ShadowDeployment(shadow_id=identity, primary_deployment_id=primary.deployment_id,
                shadow_deployment_id="", model_name=primary.model_name, primary_version=primary.version,
                shadow_version=request.shadow_version, traffic_mirror_pct=request.traffic_mirror_pct,
                status="initializing", created_at=serving_store.now(), route_id=route.route_id,
                request_id=request.request_id, request_snapshot=request.model_copy(deep=True),
                deployment_request=deploy_request, comparison_gate=request.comparison_gate)
            _save(entry)  # 모델 참조/child request ID를 실제 create 전 영속한다.
    return retry_shadow(identity)


def retry_shadow(identity):
    with serving_routes.operation("shadow-"+identity):
        entry = get_shadow(identity)
        if entry.status == "active":
            return entry
        if entry.status not in ("initializing", "failed") or entry.cleanup_pending or entry.deployment_request is None:
            raise HTTPException(status_code=409, detail="다시 기동할 shadow 의도가 없습니다")
        child = deployments.create_deployment(entry.deployment_request, defer=True)
        entry = entry.model_copy(update={"shadow_deployment_id": child.deployment_id})
        _save(entry)
        child = deployments.retry_deployment(child.deployment_id)
        if child.status != "running" or not child.verified_at:
            entry = entry.model_copy(update={"status": "failed", "error": "shadow 실제 기동/검증 실패"})
            _save(entry)
            return entry
        serving_routes.attach_shadow(entry.route_id, identity, child.deployment_id, entry.traffic_mirror_pct, entry.comparison_gate)
        entry = entry.model_copy(update={"status": "active", "error": None})
        _save(entry)
        return get_shadow(identity)


def promote_shadow(identity):
    with serving_routes.operation("shadow-"+identity):
        return _promote(identity)


def _promote(identity):
    entry = get_shadow(identity)
    if entry.status == "promoted":
        return entry
    if entry.status != "active" or not entry.route_id:
        raise HTTPException(status_code=409, detail="실제 route에 연결된 active shadow가 필요합니다")
    route = serving_routes.get_route(entry.route_id)
    if route.shadow_id != identity:
        raise HTTPException(status_code=409, detail="현재 비교 route와 다른 shadow입니다")
    serving_routes.promote(entry.route_id)
    _save(entry.model_copy(update={"status": "promoted", "promoted_at": serving_store.now()}))
    return get_shadow(identity)


def abort_shadow(identity):
    with serving_routes.operation("shadow-"+identity):
        return _abort(identity)


def _abort(identity):
    entry = get_shadow(identity)
    if entry.status == "aborted":
        return entry
    if entry.status not in ("initializing", "active", "failed"):
        raise HTTPException(status_code=409, detail="종료된 shadow는 abort할 수 없습니다")
    route = serving_routes.get_route(entry.route_id) if entry.route_id else None
    pending = False
    if route and route.shadow_id == identity:
        route = serving_routes.detach_shadow(route.route_id, identity)
        pending = route.cleanup_pending
    elif entry.shadow_deployment_id:
        stopped = deployments.stop_deployment(entry.shadow_deployment_id)
        pending = bool(stopped.container_map) or stopped.cleanup_pending or stopped.launch_pending
    aborted = entry.model_copy(update={"status": "failed" if pending else "aborted", "cleanup_pending": pending,
        "error": "shadow 정리 미확인" if pending else None, "aborted_at": None if pending else serving_store.now()})
    _save(aborted)
    return get_shadow(identity)
