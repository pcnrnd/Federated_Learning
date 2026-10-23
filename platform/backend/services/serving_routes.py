"""실제 /predict 소비 경로의 원자 전환. 네트워크는 registry 전역 잠금 밖에서 수행한다."""
import threading
import uuid

from fastapi import HTTPException

from models.serving_schemas import ServingRoute
from services import deployment_service as deployments, serving_requests, serving_store as store
from services.model_registry import REGISTRY_LOCK

_locks_guard = threading.RLock()
_locks = {}


def operation(identity):
    with _locks_guard:
        return _locks.setdefault(identity, threading.RLock())


def list_routes():
    return sorted((ServingRoute(**raw) for raw in store.read()["routes"].values()), key=lambda route: route.created_at, reverse=True)


def get_route(identity):
    raw = store.read()["routes"].get(identity)
    if raw is None:
        raise HTTPException(status_code=404, detail="serving route가 없습니다")
    return ServingRoute(**raw)


def ensure_route(primary_id):
    with REGISTRY_LOCK:
        serving_requests.deployment(primary_id)
        data = store.load()
        for raw in data["routes"].values():
            if raw["status"] != "closed" and raw["primary_deployment_id"] == primary_id:
                return ServingRoute(**raw)
        route = ServingRoute(route_id=uuid.uuid4().hex, primary_deployment_id=primary_id,
            created_at=store.now(), changed_at=store.now())
        data["routes"][route.route_id] = route.model_dump()
        store.save(data)
        return route


def reserve_shadow(route_id, shadow_id, primary_id):
    """실제 child create 전에 비교 슬롯을 영속한다. 메타 잠금 안에서만 실행한다."""
    with REGISTRY_LOCK:
        route = get_route(route_id)
        if (route.status != "active" or route.primary_deployment_id != primary_id
                or route.cleanup_pending or route.cleanup_deployment_ids
                or (route.shadow_id and route.shadow_id != shadow_id)):
            raise HTTPException(status_code=409, detail="다른 비교/정리/전환이 없는 활성 route만 예약할 수 있습니다")
        if route.shadow_id == shadow_id:
            return route
        if route.shadow_deployment_id:
            raise HTTPException(status_code=409, detail="이미 연결된 shadow 실행이 있습니다")
        reserved = route.model_copy(update={"shadow_id": shadow_id, "changed_at": store.now()})
        data = store.load()
        data["routes"][route_id] = reserved.model_dump()
        data["shadows"][shadow_id] = dict(status="initializing", route_id=route_id,
            deployment_id=None, deployment_request_id="shadow-"+shadow_id, cleanup_pending=False)
        store.save(data)  # 저장 실패 뒤 메모리의 예약만으로 실제 child를 만들지 않는다.
        return reserved


def attach_shadow(route_id, shadow_id, deployment_id, mirror_pct, gate=None):
    with operation(route_id), REGISTRY_LOCK:
        route = get_route(route_id)
        if (route.status != "active" or route.shadow_id != shadow_id or route.cleanup_pending
                or route.shadow_deployment_id not in (None, deployment_id)):
            raise HTTPException(status_code=409, detail="같은 shadow 의도가 영속 예약한 활성 route만 연결할 수 있습니다")
        primary = serving_requests.deployment(route.primary_deployment_id)
        shadow = serving_requests.deployment(deployment_id)
        if shadow.model_name != primary.model_name or shadow.deployment_id == primary.deployment_id:
            raise HTTPException(status_code=409, detail="서로 다른 실행의 같은 모델 비교가 필요합니다")
        if route.shadow_deployment_id == deployment_id and route.shadow_id == shadow_id:
            return route
        route = route.model_copy(update={"shadow_deployment_id": deployment_id, "shadow_id": shadow_id,
            "mirror_pct": mirror_pct, "comparison_gate": gate, "comparison_started_at": store.now(),
            "generation": route.generation+1, "changed_at": store.now(), "status": "active"})
        data = store.load()
        data["routes"][route_id] = route.model_dump()
        data["shadows"][shadow_id] = dict(status="active", route_id=route_id, deployment_id=deployment_id, cleanup_pending=False)
        store.save(data)
        return route


def configure_gate(route_id, gate):
    with operation(route_id), REGISTRY_LOCK:
        route = get_route(route_id)
        if route.status != "active" or not route.shadow_deployment_id:
            raise HTTPException(status_code=409, detail="활성 primary/shadow 경로가 필요합니다")
        if route.comparison_gate == gate:
            return route
        route = route.model_copy(update={"comparison_gate": gate, "comparison_started_at": store.now(),
            "generation": route.generation+1, "changed_at": store.now()})
        data = store.load()
        data["routes"][route_id] = route.model_dump()
        store.save(data)  # gate 수정 전 관측을 새 정책의 실측으로 섞지 않는다.
        return route


def _health(identity):
    deployments.reconcile_deployment(identity)
    return serving_requests.deployment(identity)


def promote(route_id):
    with operation(route_id):
        before = get_route(route_id)
        if before.status == "promoted":
            return before
        if before.status != "active" or not before.shadow_deployment_id:
            raise HTTPException(status_code=409, detail="활성 shadow가 없습니다")
        comparison = serving_requests.comparison(route_id)
        if not comparison.gate_ready:
            raise HTTPException(status_code=409, detail="; ".join(comparison.gate_reasons))
        _health(before.primary_deployment_id)
        _health(before.shadow_deployment_id)
        with REGISTRY_LOCK:
            data = store.load()
            fresh = ServingRoute(**data["routes"][route_id])
            if fresh.generation != before.generation or not serving_requests.comparison(route_id, data=data).gate_ready:
                raise HTTPException(status_code=409, detail="비교/경로 상태가 변경됐습니다")
            serving_requests.deployment(before.primary_deployment_id)
            serving_requests.deployment(before.shadow_deployment_id)
            switched = fresh.model_copy(update={"primary_deployment_id": before.shadow_deployment_id,
                "previous_deployment_id": before.primary_deployment_id, "shadow_deployment_id": None,
                "status": "promoted", "generation": fresh.generation+1, "changed_at": store.now()})
            data["routes"][route_id] = switched.model_dump()
            data["shadows"][fresh.shadow_id] = dict(status="promoted", route_id=route_id,
                deployment_id=switched.primary_deployment_id, cleanup_pending=False, changed_at=store.now())
            store.save(data)  # 응답 유실/재시작에도 predict가 읽는 authoritative route 자체를 전환.
            return switched


def rollback(route_id):
    with operation(route_id):
        before = get_route(route_id)
        if before.status == "rolled_back":
            return before
        if before.status != "promoted" or not before.previous_deployment_id:
            raise HTTPException(status_code=409, detail="복원할 이전 정상 route가 없습니다")
        _health(before.previous_deployment_id)
        with REGISTRY_LOCK:
            data = store.load()
            fresh = ServingRoute(**data["routes"][route_id])
            if fresh.generation != before.generation:
                raise HTTPException(status_code=409, detail="복원 중 route가 변경됐습니다")
            serving_requests.deployment(before.previous_deployment_id)
            restored = fresh.model_copy(update={"primary_deployment_id": before.previous_deployment_id,
                "previous_deployment_id": before.primary_deployment_id, "status": "rolled_back",
                "generation": fresh.generation+1, "changed_at": store.now()})
            data["routes"][route_id] = restored.model_dump()
            data["shadows"][fresh.shadow_id] = dict(status="rolled_back", route_id=route_id,
                deployment_id=before.primary_deployment_id, cleanup_pending=False, changed_at=store.now())
            store.save(data)
            return restored  # 이전/새 실행은 standby로 참조 유지. 정리 완료라고 표시하지 않는다.


def detach_shadow(route_id, shadow_id, *, deployment_ids=()):
    with operation(route_id), REGISTRY_LOCK:
        route = get_route(route_id)
        if route.shadow_id != shadow_id or route.status not in ("active", "closed"):
            raise HTTPException(status_code=409, detail="현재 active shadow만 해제할 수 있습니다")
        pending = list(route.cleanup_deployment_ids)
        for identity in (*deployment_ids, route.shadow_deployment_id):
            if identity and identity not in pending:
                pending.append(identity)
        route = route.model_copy(update={"shadow_deployment_id": None, "cleanup_deployment_ids": pending,
            "cleanup_pending": bool(pending), "generation": route.generation+1, "changed_at": store.now()})
        data = store.load()
        data["routes"][route_id] = route.model_dump()
        data["shadows"][shadow_id] = dict(status="failed", route_id=route_id,
            deployment_id=pending[-1] if pending else None, cleanup_pending=bool(pending))
        store.save(data)
    return cleanup(route_id)


def close(route_id):
    with operation(route_id), REGISTRY_LOCK:
        route = get_route(route_id)
        data = store.load()
        pending = set(route.cleanup_deployment_ids)
        if route.status != "closed":
            pending.update(value for value in (route.primary_deployment_id, route.shadow_deployment_id, route.previous_deployment_id) if value)
            request_id = data["shadows"].get(route.shadow_id, {}).get("deployment_request_id")
            if request_id:
                pending.update(entry.deployment_id for entry in deployments.list_deployments()
                    if entry.configuration and entry.configuration.request_id == request_id)
        closed = route.model_copy(update={"status": "closed", "shadow_deployment_id": None,
            "cleanup_deployment_ids": sorted(pending), "cleanup_pending": bool(pending),
            "generation": route.generation+1, "changed_at": store.now()})
        data["routes"][route_id] = closed.model_dump()
        if route.shadow_id:
            data["shadows"][route.shadow_id] = {**data["shadows"].get(route.shadow_id, {}), "status": "failed",
                "route_id": route_id, "deployment_id": route.shadow_deployment_id, "cleanup_pending": bool(pending)}
        store.save(data)  # 신규 요청을 먼저 금지한다. 진행 중 request pin은 보존한다.
    return cleanup(route_id)


def cleanup(route_id):
    with operation(route_id):
        route = get_route(route_id)
        remaining = []
        for identity in route.cleanup_deployment_ids:
            try:
                stopped = deployments.stop_deployment(identity)
                if stopped.container_map or stopped.cleanup_pending or stopped.launch_pending:
                    remaining.append(identity)
            except Exception:  # 미확인 정리를 성공으로 표시하거나 입력/Docker 예외 문자열을 저장하지 않는다.
                remaining.append(identity)
        with REGISTRY_LOCK:
            fresh = get_route(route_id)
            fresh = fresh.model_copy(update={"cleanup_deployment_ids": remaining, "cleanup_pending": bool(remaining),
                "error": "진행 요청 또는 실제 실행의 정리가 미확인입니다" if remaining else None, "changed_at": store.now()})
            data = store.load()
            for outcome in data["shadows"].values():
                if outcome["route_id"] == route_id and outcome.get("cleanup_pending"):
                    outcome.update(status="failed" if remaining else "aborted", cleanup_pending=bool(remaining))
            if not remaining and fresh.shadow_deployment_id is None and fresh.status == "active":
                fresh = fresh.model_copy(update={"shadow_id": None})
            data["routes"][route_id] = fresh.model_dump()
            store.save(data)
            return fresh
