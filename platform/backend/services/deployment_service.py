"""배포 오케스트레이션 서비스"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from threading import RLock

from docker.errors import DockerException, NotFound
from fastapi import HTTPException

from config.registry_manager import load_deployments, save_deployments
from models.common_schemas import DeploymentReconcileResult
from models.packaging_schemas import DeploymentEntry, DeploymentRequest, DeploymentTargetResult
from services import deployment_runtime, model_registry
from services.deployment_strategies import (
    NodeDeployContext,
    get_strategy,
)
from services.docker_service import get_docker_client, get_docker_hosts, refresh_docker_hosts
from services.model_registry import get_model

logger = logging.getLogger(__name__)
_operation_locks: dict[str, RLock] = {}
_locks_guard = RLock()


def _operation_lock(identity):
    with _locks_guard:
        return _operation_locks.setdefault(identity, RLock())


def _serialized_operation(function):
    @wraps(function)
    def wrapped(deployment_id, *args, **kwargs):
        with _operation_lock(deployment_id):
            return function(deployment_id, *args, **kwargs)
    return wrapped


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save(entry: DeploymentEntry) -> None:
    with model_registry.REGISTRY_LOCK:
        deployments = load_deployments()
        deployments[entry.deployment_id] = entry.model_dump()
        save_deployments(deployments)


def list_deployments() -> list[DeploymentEntry]:
    with model_registry.REGISTRY_LOCK:
        raw = load_deployments()
    return [DeploymentEntry(**v) for v in raw.values()]


def get_deployment(deployment_id: str) -> DeploymentEntry:
    with model_registry.REGISTRY_LOCK:
        raw = load_deployments()
    if deployment_id not in raw:
        raise HTTPException(status_code=404, detail="배포 기록을 찾을 수 없습니다")
    return DeploymentEntry(**raw[deployment_id])


def _latest_active_for(model_name: str) -> DeploymentEntry | None:
    """동일 모델의 가장 최근 running/pending 배포를 반환"""
    candidates = [
        d for d in list_deployments()
        if d.model_name == model_name and d.status == "running" and d.verified_at and not d.is_schedule
    ]
    candidates.sort(key=lambda d: d.created_at, reverse=True)
    return candidates[0] if candidates else None


def create_deployment(request: DeploymentRequest, *, defer=False) -> DeploymentEntry:
    """배포를 생성한다.

    1. 모델 레지스트리에서 메타 검증
    2. 노드별 Docker 클라이언트 획득
    3. 전략에 위임하여 노드마다 컨테이너 생성
    4. 결과를 deployments.yaml에 기록
    """
    # 모델 존재 검증
    if request.request_id:
        with model_registry.REGISTRY_LOCK:
            for previous_request in list_deployments():
                saved = previous_request.configuration
                if saved and saved.request_id == request.request_id and previous_request.schedule_parent_id is None:
                    if saved.model_dump() != request.model_dump():
                        raise HTTPException(status_code=409, detail="같은 배포 요청 ID의 다른 실행 설정입니다")
                    return previous_request
    _require_active(request)

    refresh_docker_hosts()
    hosts = get_docker_hosts()
    strategy = get_strategy(request.strategy)

    # 노드 유효성 사전 검증 (실패 시 어떤 컨테이너도 만들지 않음)
    for node_id in request.target_node_ids:
        if node_id not in hosts:
            raise HTTPException(
                status_code=404,
                detail=f"알 수 없는 노드: {node_id}",
            )

    # image_tag 보정 (미지정 시 기본 패턴)
    image_tag = request.image_tag or f"fed-model-{request.model_name}:{request.version}"
    request_resolved = request.model_copy(update={"image_tag": image_tag})

    deployment_id = uuid.uuid4().hex
    with _operation_lock(deployment_id):
        # 모델의 active 확인과 영속 pending 참조 예약은 archive/delete와 같은 임계구간이다.
        # Docker는 이 잠금을 해제한 뒤 실행한다. 예약 쓰기 실패면 기동하지 않는다.
        with model_registry.REGISTRY_LOCK:
            # 동시 동일 request_id의 최초 예약도 같은 잠금 안에서 다시 확인한다.
            if request.request_id:
                for previous_request in list_deployments():
                    saved = previous_request.configuration
                    if saved and saved.request_id == request.request_id and previous_request.schedule_parent_id is None:
                        if saved.model_dump() != request.model_dump():
                            raise HTTPException(status_code=409, detail="같은 배포 요청 ID의 다른 실행 설정입니다")
                        return previous_request
            model = _require_active(request)
            try:
                image_id, identity = deployment_runtime.pinned_package(model, request)
                deployment_runtime.probe_inputs(model, request)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            previous = _latest_active_for(request.model_name)
            scheduled = request.strategy == "batch"
            created_at = _now_iso()
            entry = DeploymentEntry(deployment_id=deployment_id, model_name=request.model_name,
                version=request.version, image_tag=request.image_tag or image_id, strategy=request.strategy, configuration=request.model_copy(deep=True),
                target_node_ids=list(request.target_node_ids), status="pending", created_at=created_at,
                previous_deployment_id=previous.deployment_id if previous else None, launch_pending=not scheduled,
                expected_image_id=image_id, expected_identity=identity, is_schedule=scheduled, schedule_active=scheduled,
                interval_seconds=request.interval_seconds,
                next_due_at=(datetime.fromisoformat(created_at)+timedelta(seconds=request.interval_seconds)).isoformat() if scheduled else None,
                target_results={node: DeploymentTargetResult() for node in request.target_node_ids})
            _save(entry)
        if scheduled or defer:
            return entry
        return _launch(entry, request_resolved, hosts, strategy)


def _require_active(request):
    entry = get_model(request.model_name, request.version)
    if entry.status != "active":
        raise HTTPException(status_code=409, detail="보관한 모델은 일반 배포할 수 없습니다")
    return entry


def _launch(entry, request_resolved, hosts, strategy):
    if entry.configuration is None or not entry.expected_image_id:
        raise HTTPException(status_code=409, detail="복구 가능한 실행 설정/이미지 snapshot이 없습니다")
    model = _require_active(entry.configuration)
    request_resolved = entry.configuration.model_copy(update={"image_tag": entry.expected_image_id})
    container_map = dict(entry.container_map)
    results = dict(entry.target_results)
    for node_id in entry.target_node_ids:
        client = None
        results[node_id] = DeploymentTargetResult(status="launching", container_id=container_map.get(node_id))
        entry = entry.model_copy(update={"target_results": dict(results), "launch_pending": True})
        _save(entry)  # 실제 create 전에 대상 실행 의도를 영속한다.
        try:
            client = get_docker_client(node_id)
            deployment_runtime.ensure_image(client, entry.expected_image_id, entry.expected_identity)
            ctx = NodeDeployContext(
                node_id=node_id,
                docker_client=client,
                node_info=hosts[node_id],
            )
            result = strategy.deploy_to_node(ctx, request_resolved, entry.deployment_id)
            container_map[result.node_id] = result.container_id
            entry = entry.model_copy(update={"container_map": dict(container_map)})
            _save(entry)
            container = client.containers.get(result.container_id)
            results[node_id] = deployment_runtime.verify_target(client, container, hosts[node_id], entry, model, request_resolved)
        except (HTTPException, DockerException, OSError, ValueError, TypeError, KeyError) as exc:
            # 독립된 다른 대상은 계속 시도한다. response body/env/입력 행은 저장하지 않는다.
            results[node_id] = DeploymentTargetResult(status="failed", container_id=container_map.get(node_id),
                                                       error_code=type(exc).__name__)
        finally:
            if client is not None:
                try:
                    client.close()
                except (DockerException, OSError):
                    pass
        entry = entry.model_copy(update={"container_map": dict(container_map), "target_results": dict(results)})
        _save(entry)
    failed = any(result.status != "running" for result in results.values())
    entry = entry.model_copy(update={"status": "failed" if failed else "running",
        "launch_pending": failed, "verified_at": None if failed else _now_iso(),
        "error": "일부 대상의 실제 기동/예측 검증 실패" if failed else None})
    _save(entry)
    return entry


@_serialized_operation
def retry_deployment(deployment_id):
    entry = get_deployment(deployment_id)
    if entry.is_schedule:
        from services.deployment_scheduling import retry_schedule
        return retry_schedule(entry)
    if entry.status in ("stopped", "rolled_back"):
        raise HTTPException(status_code=409, detail="정지한 실행은 새 배포 요청으로 시작하세요")
    if entry.cleanup_pending:
        raise HTTPException(status_code=409, detail="미확인 정리를 먼저 정지 요청으로 완료하세요")
    if entry.status == "running" and entry.verified_at:
        reconcile_deployment(deployment_id)
        return get_deployment(deployment_id)
    refresh_docker_hosts()
    return _launch(entry, entry.configuration, get_docker_hosts(), get_strategy(entry.strategy))


@_serialized_operation
def stop_deployment(deployment_id: str) -> DeploymentEntry:
    """배포된 컨테이너들을 모두 정지/제거"""
    entry = get_deployment(deployment_id)
    if entry.is_schedule:
        from services.deployment_scheduling import stop_schedule
        return stop_schedule(entry)
    with model_registry.REGISTRY_LOCK:
        from services import serving_store
        if serving_store.references(deployment_id):
            raise HTTPException(status_code=409, detail="실제 route/standby 또는 진행 요청이 참조하는 실행입니다")
        entry = get_deployment(deployment_id)
        entry = entry.model_copy(update={"cleanup_pending": True})
        _save(entry)  # route 신규 binding과 같은 lock에서 정리 의도를 먼저 예약한다.
    refresh_docker_hosts()
    if entry.status == "pending" and not entry.container_map:
        # 이 표시 도입 이전의 빈 pending도 기동 부재의 증거가 아니다.
        entry = entry.model_copy(update={"launch_pending": True})
        _save(entry)

    remaining = dict(entry.container_map)
    outcomes = dict(entry.cleanup_results)
    unresolved = False
    nodes = set(remaining) | (set(entry.target_node_ids) if entry.launch_pending else set())
    for node_id in sorted(nodes):
        try:
            client = get_docker_client(node_id)
            _cleanup_node(client, node_id, remaining, entry)
            remaining.pop(node_id, None)
            outcomes[node_id] = "removed_or_confirmed_absent"
        except (DockerException, HTTPException, ValueError) as exc:
            unresolved = True
            outcomes[node_id] = f"unknown:{type(exc).__name__}"
            logger.warning("컨테이너 정리 미확인: deployment=%s node=%s", deployment_id, node_id)
        # 각 대상 확인 후 영속한다. 중단된 제거는 다음 재시도에서 NotFound로 확인한다.
        entry = entry.model_copy(update={"container_map": dict(remaining), "cleanup_results": dict(outcomes),
            "cleanup_pending": True, "status": "failed"})
        _save(entry)
    pending = unresolved or bool(remaining)
    entry = entry.model_copy(update={"status": "failed" if pending else "stopped",
        "container_map": remaining, "cleanup_pending": pending,
        "launch_pending": entry.launch_pending if pending else False,
        "error": "일부 대상의 컨테이너 정리를 확인할 수 없습니다" if pending else None})
    _save(entry)
    return entry


def _cleanup_node(client, node_id, remaining, entry):
    targets = {}
    known = remaining.get(node_id)
    if known:
        try:
            targets[known] = client.containers.get(known)
        except NotFound:
            pass
    if entry.launch_pending:
        # 생성 응답/중간 저장 유실로 map에 없는 컨테이너도 배포의 예약 ID로 확인한다.
        discovered = client.containers.list(all=True, filters={"label": f"fed.deployment_id={entry.deployment_id}"})
        for container in discovered:
            labels = getattr(container, "labels", None)
            if (not isinstance(container.id, str) or not isinstance(labels, dict)
                    or labels.get("fed.deployment_id") != entry.deployment_id):
                raise ValueError("예약한 배포의 컨테이너 정체성을 확인할 수 없습니다")
            targets[container.id] = container
    for identity, container in targets.items():
        try:
            container.stop(timeout=10)
            container.remove(force=True)
        except NotFound:
            pass
        except DockerException:
            remaining[node_id] = identity
            raise


def rollback_deployment(deployment_id: str) -> DeploymentEntry:
    """이전 배포로 롤백 — 현재 배포를 정지하고 previous를 다시 활성화"""
    snapshot = get_deployment(deployment_id)
    if snapshot.schedule_parent_id:
        # tick/stop와 같은 parent→child 잠금 순서. 복원 뒤 자동 다음 회차가 덮어쓰지 않는다.
        with _operation_lock(snapshot.schedule_parent_id):
            parent = get_deployment(snapshot.schedule_parent_id)
            if parent.current_run_id == snapshot.rollback_run_id and snapshot.rollback_run_id:
                reconcile_deployment(snapshot.rollback_run_id)
                return get_deployment(snapshot.rollback_run_id)
            if parent.current_run_id != deployment_id or parent.opening_run_id:
                raise HTTPException(status_code=409, detail="진행 중인 다음 회차가 없는 현재 batch 실행만 복원하세요")
            _save(parent.model_copy(update={"schedule_active": False}))
            with _operation_lock(deployment_id):
                restored = _rollback(deployment_id)
            parent = get_deployment(snapshot.schedule_parent_id)
            _save(parent.model_copy(update={"current_run_id": restored.deployment_id, "opening_run_id": None,
                "schedule_active": False, "status": "pending", "error": "회차 복원 완료; 자동 일정 중지"}))
            return restored
    with _operation_lock(deployment_id):
        return _rollback(deployment_id)


def _rollback(deployment_id):
    current = get_deployment(deployment_id)
    with model_registry.REGISTRY_LOCK:
        from services import serving_store
        if serving_store.references(deployment_id):
            raise HTTPException(status_code=409, detail="serving route가 참조하는 실행은 route rollback을 사용하세요")
    if current.is_schedule:
        raise HTTPException(status_code=409, detail="실제 검증된 실행 회차를 선택해 rollback하세요")
    if not current.previous_deployment_id:
        raise HTTPException(
            status_code=400,
            detail="롤백 가능한 이전 배포가 없습니다",
        )
    previous = get_deployment(current.previous_deployment_id)
    if not previous.configuration or not previous.verified_at or not previous.expected_image_id:
        raise HTTPException(status_code=409, detail="이전 정상 실행의 전체 설정/검증 snapshot이 없습니다")
    if current.rollback_run_id:
        restored = _restore_entry(previous, current.rollback_run_id)
    else:
        identity = uuid.uuid4().hex
        current = current.model_copy(update={"rollback_run_id": identity})
        _save(current)  # 복원 실행 게시 응답 유실도 같은 ID로 재연결한다.
        restored = _restore_entry(previous, identity)
    if restored.status != "running" or not restored.verified_at:
        restored = retry_deployment(restored.deployment_id)
    else:
        reconcile_deployment(restored.deployment_id)
        restored = get_deployment(restored.deployment_id)
    if restored.status != "running":
        raise HTTPException(status_code=409, detail="이전 정상 설정의 실제 복원 검증 실패")
    stopped = stop_deployment(current.deployment_id)
    if stopped.cleanup_pending or stopped.launch_pending or stopped.container_map:
        raise HTTPException(status_code=409, detail="복원은 확인됐으나 현재 실행의 정리 확인이 필요합니다")
    _save(stopped.model_copy(update={"status": "rolled_back", "rollback_run_id": restored.deployment_id}))
    return restored


def _restore_entry(previous, identity, *, extra=None):
    try:
        return get_deployment(identity)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    with _operation_lock(identity), model_registry.REGISTRY_LOCK:
        _require_active(previous.configuration)
        restored = previous.model_copy(deep=True, update={"deployment_id": identity, "status": "pending",
            "configuration": previous.configuration.model_copy(update={"request_id": None}),
            "created_at": _now_iso(), "container_map": {}, "target_results": {}, "verified_at": None,
            "launch_pending": True, "cleanup_pending": False, "cleanup_results": {}, "error": None,
            "previous_deployment_id": previous.deployment_id, "rollback_run_id": None,
            "schedule_parent_id": None, "is_schedule": False, "schedule_active": False,
            "current_run_id": None, "opening_run_id": None, **(extra or {})})
        _save(restored)
    return restored


def _inspect_container_state(node_id: str, container_id: str) -> str | None:
    """Docker API로 컨테이너 상태를 조회한다. 없으면 None."""
    try:
        client = get_docker_client(node_id)
        container = client.containers.get(container_id)
        return container.status
    except NotFound:
        return None
    except DockerException as exc:
        logger.warning("컨테이너 상태 조회 실패 (%s @ %s): %s", container_id, node_id, exc)
        return "unknown"


@_serialized_operation
def reconcile_deployment(deployment_id: str) -> DeploymentReconcileResult:
    """저장된 배포 상태와 Docker 런타임 상태를 대조해 기록을 정정한다."""
    entry = get_deployment(deployment_id)
    previous_status = entry.status
    changes: list[str] = []
    container_states: dict[str, str] = {}
    if entry.is_schedule:
        return DeploymentReconcileResult(deployment_id=deployment_id, previous_status=previous_status,
            current_status=entry.status, reconciled=False, changes=[], container_states={})

    if (entry.configuration is not None and entry.verified_at and not entry.cleanup_pending
            and entry.status in ("running", "pending", "failed")):
        model = get_model(entry.model_name, entry.version)
        refresh_docker_hosts()
        results = dict(entry.target_results)
        for node in entry.target_node_ids:
            client = None
            try:
                client = get_docker_client(node)
                container = client.containers.get(entry.container_map[node])
                results[node] = deployment_runtime.verify_target(client, container, get_docker_hosts()[node],
                    entry, model, entry.configuration, timeout=3)
            except (HTTPException, DockerException, OSError, ValueError, KeyError, TypeError) as exc:
                results[node] = DeploymentTargetResult(status="failed", container_id=entry.container_map.get(node),
                    error_code=type(exc).__name__)
            finally:
                if client is not None:
                    client.close()
        failed = any(result.status != "running" for result in results.values())
        entry = entry.model_copy(update={"target_results": results, "status": "failed" if failed else "running",
            "error": "실제 health/predict 재검증 실패" if failed else None})
        _save(entry)
        return DeploymentReconcileResult(deployment_id=deployment_id, previous_status=previous_status,
            current_status=entry.status, reconciled=entry.status != previous_status,
            changes=["고정 이미지/health/실제 predict 재검증"],
            container_states={node: value.status for node, value in results.items()})

    if entry.launch_pending or entry.cleanup_pending or (entry.status == "pending" and not entry.container_map):
        # 재시작/실패 후 미확인 예약을 빈 map이라는 이유로 해제하지 않는다.
        return DeploymentReconcileResult(deployment_id=deployment_id, previous_status=previous_status,
            current_status=entry.status, reconciled=False, changes=["미확인 기동/정리 참조 보존"],
            container_states={})

    if not entry.container_map:
        if entry.status in {"running", "pending"}:
            new_status = "failed"
            changes.append("container_map이 비어 있어 failed로 정정")
            entry = entry.model_copy(update={"status": new_status, "error": "컨테이너 없음"})
            _save(entry)
            return DeploymentReconcileResult(
                deployment_id=deployment_id,
                previous_status=previous_status,
                current_status=new_status,
                reconciled=True,
                changes=changes,
                container_states=container_states,
            )
        return DeploymentReconcileResult(
            deployment_id=deployment_id,
            previous_status=previous_status,
            current_status=entry.status,
            reconciled=False,
            changes=changes,
            container_states=container_states,
        )

    refresh_docker_hosts()
    for node_id, container_id in entry.container_map.items():
        state = _inspect_container_state(node_id, container_id)
        if state is None:
            container_states[node_id] = "missing"
            changes.append(f"컨테이너 없음: {node_id}/{container_id[:12]}")
        else:
            container_states[node_id] = state

    new_status = entry.status
    if entry.status in {"running", "pending"}:
        states = list(container_states.values())
        if all(s == "missing" for s in states):
            new_status = "failed"
            changes.append("모든 컨테이너가 사라져 failed로 정정")
        elif any(s == "missing" for s in states):
            new_status = "failed"
            changes.append("일부 컨테이너가 사라져 failed로 정정")
        elif all(s in {"exited", "dead", "created"} for s in states):
            new_status = "stopped"
            changes.append("컨테이너가 종료되어 stopped로 정정")
        elif any(s not in {"running"} for s in states if s != "missing"):
            new_status = "failed"
            changes.append("일부 컨테이너가 비정상 상태")

    reconciled = new_status != previous_status
    if reconciled:
        update_fields: dict[str, object] = {"status": new_status}
        if new_status == "failed" and not entry.error:
            update_fields["error"] = "; ".join(changes)
        entry = entry.model_copy(update=update_fields)
        _save(entry)
        logger.info(
            "배포 reconcile: id=%s %s → %s (%s)",
            deployment_id,
            previous_status,
            new_status,
            changes,
        )

    return DeploymentReconcileResult(
        deployment_id=deployment_id,
        previous_status=previous_status,
        current_status=new_status,
        reconciled=reconciled,
        changes=changes,
        container_states=container_states,
    )


def reconcile_all_active() -> list[DeploymentReconcileResult]:
    """running/pending 배포 전체에 reconcile을 적용한다."""
    targets = [
        d for d in list_deployments() if d.status in {"running", "pending"}
    ]
    return [reconcile_deployment(d.deployment_id) for d in targets]
