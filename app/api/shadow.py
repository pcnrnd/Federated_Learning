"""섀도우 배포 API"""
from __future__ import annotations

from fastapi import APIRouter, Query

from models.maintenance_schemas import (
    ShadowDeployment,
    ShadowDeploymentRequest,
)
from services import shadow_deployment_service

router = APIRouter(prefix="/api/shadow-deployments", tags=["shadow-deployments"])


@router.get("", response_model=list[ShadowDeployment])
def list_shadows_endpoint(
    status: str | None = Query(default=None),
) -> list[ShadowDeployment]:
    return shadow_deployment_service.list_shadows(status=status)


@router.post("", response_model=ShadowDeployment, status_code=201)
def create_shadow_endpoint(request: ShadowDeploymentRequest) -> ShadowDeployment:
    return shadow_deployment_service.create_shadow(request)


@router.get("/{shadow_id}", response_model=ShadowDeployment)
def get_shadow_endpoint(shadow_id: str) -> ShadowDeployment:
    return shadow_deployment_service.get_shadow(shadow_id)


@router.post("/{shadow_id}/promote", response_model=ShadowDeployment)
def promote_endpoint(shadow_id: str) -> ShadowDeployment:
    return shadow_deployment_service.promote_shadow(shadow_id)


@router.post("/{shadow_id}/abort", response_model=ShadowDeployment)
def abort_endpoint(shadow_id: str) -> ShadowDeployment:
    return shadow_deployment_service.abort_shadow(shadow_id)
