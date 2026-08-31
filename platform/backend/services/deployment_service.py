"""배포 오케스트레이션 서비스"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from docker.errors import DockerException, NotFound
from fastapi import HTTPException

from config.registry_manager import load_deployments, save_deployments
from models.common_schemas import DeploymentReconcileResult
from models.packaging_schemas import DeploymentEntry, DeploymentRequest
from services.deployment_strategies import (
    NodeDeployContext,
    get_strategy,
)
from services.docker_service import get_docker_client, get_docker_hosts, refresh_docker_hosts
from services.model_registry import get_model

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save(entry: DeploymentEntry) -> None:
    deployments = load_deployments()
    deployments[entry.deployment_id] = entry.model_dump()
    save_deployments(deployments)


def list_deployments() -> list[DeploymentEntry]:
    raw = load_deployments()
    return [DeploymentEntry(**v) for v in raw.values()]


def get_deployment(deployment_id: str) -> DeploymentEntry:
    raw = load_deployments()
    if deployment_id not in raw:
        raise HTTPException(status_code=404, detail="배포 기록을 찾을 수 없습니다")
    return DeploymentEntry(**raw[deployment_id])


def _latest_active_for(model_name: str) -> DeploymentEntry | None:
    """동일 모델의 가장 최근 running/pending 배포를 반환"""
    candidates = [
        d for d in list_deployments()
        if d.model_name == model_name and d.status in {"running", "pending"}
    ]
    candidates.sort(key=lambda d: d.created_at, reverse=True)
    return candidates[0] if candidates else None


def create_deployment(request: DeploymentRequest) -> DeploymentEntry:
    """배포를 생성한다.

    1. 모델 레지스트리에서 메타 검증
    2. 노드별 Docker 클라이언트 획득
    3. 전략에 위임하여 노드마다 컨테이너 생성
    4. 결과를 deployments.yaml에 기록
    """
    # 모델 존재 검증
    get_model(request.model_name, request.version)

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
    previous = _latest_active_for(request.model_name)

    entry = DeploymentEntry(
        deployment_id=deployment_id,
        model_name=request.model_name,
        version=request.version,
        image_tag=image_tag,
        strategy=request.strategy,
        target_node_ids=list(request.target_node_ids),
        container_map={},
        status="pending",
        created_at=_now_iso(),
        previous_deployment_id=previous.deployment_id if previous else None,
    )
    _save(entry)

    container_map: dict[str, str] = {}
    try:
        for node_id in request.target_node_ids:
            client = get_docker_client(node_id)
            ctx = NodeDeployContext(
                node_id=node_id,
                docker_client=client,
                node_info=hosts[node_id],
            )
            result = strategy.deploy_to_node(ctx, request_resolved, deployment_id)
            container_map[result.node_id] = result.container_id
    except HTTPException:
        entry = entry.model_copy(
            update={"status": "failed", "container_map": container_map},
        )
        _save(entry)
        raise
    except DockerException as exc:
        entry = entry.model_copy(
            update={
                "status": "failed",
                "container_map": container_map,
                "error": str(exc),
            }
        )
        _save(entry)
        raise HTTPException(status_code=500, detail=f"배포 실패: {exc}") from exc

    entry = entry.model_copy(
        update={"status": "running", "container_map": container_map},
    )
    _save(entry)
    logger.info(
        "배포 완료: id=%s strategy=%s model=%s@%s nodes=%s",
        deployment_id,
        request.strategy,
        request.model_name,
        request.version,
        list(container_map.keys()),
    )
    return entry


def stop_deployment(deployment_id: str) -> DeploymentEntry:
    """배포된 컨테이너들을 모두 정지/제거"""
    entry = get_deployment(deployment_id)
    refresh_docker_hosts()

    for node_id, container_id in entry.container_map.items():
        try:
            client = get_docker_client(node_id)
            container = client.containers.get(container_id)
            container.stop(timeout=10)
            container.remove(force=True)
        except NotFound:
            logger.warning("이미 제거된 컨테이너: %s @ %s", container_id, node_id)
        except DockerException as exc:
            logger.error("컨테이너 정리 실패 (%s @ %s): %s", container_id, node_id, exc)

    entry = entry.model_copy(update={"status": "stopped"})
    _save(entry)
    return entry


def rollback_deployment(deployment_id: str) -> DeploymentEntry:
    """이전 배포로 롤백 — 현재 배포를 정지하고 previous를 다시 활성화"""
    current = get_deployment(deployment_id)
    if not current.previous_deployment_id:
        raise HTTPException(
            status_code=400,
            detail="롤백 가능한 이전 배포가 없습니다",
        )
    previous = get_deployment(current.previous_deployment_id)

    stop_deployment(current.deployment_id)
    current = get_deployment(current.deployment_id)
    current = current.model_copy(update={"status": "rolled_back"})
    _save(current)

    # 이전 배포를 동일한 구성으로 재배포
    request = DeploymentRequest(
        model_name=previous.model_name,
        version=previous.version,
        strategy=previous.strategy,
        target_node_ids=previous.target_node_ids,
        image_tag=previous.image_tag,
    )
    new_entry = create_deployment(request)
    logger.info(
        "롤백: %s → %s (model=%s@%s)",
        deployment_id,
        new_entry.deployment_id,
        previous.model_name,
        previous.version,
    )
    return new_entry


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


def reconcile_deployment(deployment_id: str) -> DeploymentReconcileResult:
    """저장된 배포 상태와 Docker 런타임 상태를 대조해 기록을 정정한다."""
    entry = get_deployment(deployment_id)
    previous_status = entry.status
    changes: list[str] = []
    container_states: dict[str, str] = {}

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
