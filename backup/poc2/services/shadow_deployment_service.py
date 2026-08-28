"""섀도우 배포 서비스 — primary 배포 옆에 신규 버전을 동시 배포하고,
   promote 시 신규 → primary 승격(기존 primary 롤백) 또는 abort 시 신규만 정지.

실제 트래픽 미러링은 외부 프록시 책임. 본 서비스는 배포 짝과 라이프사이클을 관리한다.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from config.maintenance_manager import load_shadows, save_shadows
from models.maintenance_schemas import (
    ShadowDeployment,
    ShadowDeploymentRequest,
)
from models.packaging_schemas import DeploymentRequest
from services import deployment_service
from services.model_registry import get_model

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save(entry: ShadowDeployment) -> None:
    shadows = load_shadows()
    shadows[entry.shadow_id] = entry.model_dump()
    save_shadows(shadows)


def list_shadows(status: str | None = None) -> list[ShadowDeployment]:
    raw = load_shadows()
    shadows = [ShadowDeployment(**v) for v in raw.values()]
    if status:
        shadows = [s for s in shadows if s.status == status]
    shadows.sort(key=lambda s: s.created_at, reverse=True)
    return shadows


def get_shadow(shadow_id: str) -> ShadowDeployment:
    raw = load_shadows()
    if shadow_id not in raw:
        raise HTTPException(status_code=404, detail="섀도우 배포를 찾을 수 없습니다")
    return ShadowDeployment(**raw[shadow_id])


def create_shadow(request: ShadowDeploymentRequest) -> ShadowDeployment:
    primary = deployment_service.get_deployment(request.primary_deployment_id)
    if primary.status != "running":
        raise HTTPException(
            status_code=409,
            detail=f"primary 배포가 running 상태가 아닙니다 (현재: {primary.status})",
        )
    # 섀도우 버전은 레지스트리에 등록되어 있어야 한다
    get_model(primary.model_name, request.shadow_version)

    target_nodes = request.target_node_ids or list(primary.target_node_ids)

    shadow_deploy_request = DeploymentRequest(
        model_name=primary.model_name,
        version=request.shadow_version,
        strategy=primary.strategy,
        target_node_ids=target_nodes,
        image_tag=request.image_tag,
        container_name_prefix=f"shadow-{primary.model_name}",
        labels={
            "fed.role": "shadow",
            "fed.primary_deployment": primary.deployment_id,
            "fed.traffic_mirror_pct": str(request.traffic_mirror_pct),
        },
    )
    shadow_deployment = deployment_service.create_deployment(shadow_deploy_request)

    shadow = ShadowDeployment(
        shadow_id=uuid.uuid4().hex,
        primary_deployment_id=primary.deployment_id,
        shadow_deployment_id=shadow_deployment.deployment_id,
        model_name=primary.model_name,
        primary_version=primary.version,
        shadow_version=request.shadow_version,
        traffic_mirror_pct=request.traffic_mirror_pct,
        status="active",
        created_at=_now_iso(),
    )
    _save(shadow)
    logger.info(
        "섀도우 생성: %s (primary=%s@%s, shadow=%s@%s, mirror=%.0f%%)",
        shadow.shadow_id,
        primary.deployment_id,
        primary.version,
        shadow_deployment.deployment_id,
        request.shadow_version,
        request.traffic_mirror_pct,
    )
    return shadow


def promote_shadow(shadow_id: str) -> ShadowDeployment:
    """섀도우를 primary로 승격하고 기존 primary는 정지"""
    shadow = get_shadow(shadow_id)
    if shadow.status != "active":
        raise HTTPException(
            status_code=409,
            detail=f"active 상태에서만 promote 가능합니다 (현재: {shadow.status})",
        )
    # 기존 primary 정지
    deployment_service.stop_deployment(shadow.primary_deployment_id)

    promoted = shadow.model_copy(
        update={"status": "promoted", "promoted_at": _now_iso()}
    )
    _save(promoted)
    logger.info(
        "섀도우 promote: %s — primary %s 정지, %s가 새 primary",
        shadow_id,
        shadow.primary_deployment_id,
        shadow.shadow_deployment_id,
    )
    return promoted


def abort_shadow(shadow_id: str) -> ShadowDeployment:
    """섀도우 폐기 — shadow 배포 정지, primary 유지"""
    shadow = get_shadow(shadow_id)
    if shadow.status != "active":
        raise HTTPException(
            status_code=409,
            detail=f"active 상태에서만 abort 가능합니다 (현재: {shadow.status})",
        )
    deployment_service.stop_deployment(shadow.shadow_deployment_id)

    aborted = shadow.model_copy(
        update={"status": "aborted", "aborted_at": _now_iso()}
    )
    _save(aborted)
    logger.info("섀도우 abort: %s — shadow %s 정지", shadow_id, shadow.shadow_deployment_id)
    return aborted
