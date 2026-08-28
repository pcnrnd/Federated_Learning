"""모델 배포 API 엔드포인트"""
from __future__ import annotations

from fastapi import APIRouter, Header, Response

from models.common_schemas import DeploymentReconcileResult
from models.packaging_schemas import DeploymentEntry, DeploymentRequest
from services import deployment_service, idempotency

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


@router.get("", response_model=list[DeploymentEntry])
def list_deployments_endpoint() -> list[DeploymentEntry]:
    """모든 배포 기록"""
    return deployment_service.list_deployments()


@router.post("", response_model=DeploymentEntry, status_code=201)
def create_deployment_endpoint(
    request: DeploymentRequest,
    response: Response,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> DeploymentEntry:
    """새 배포 생성 (realtime / batch / edge) — X-Idempotency-Key 지원"""
    endpoint = "POST /api/deployments"
    is_new, cached, status = idempotency.begin(x_idempotency_key, endpoint, request)
    if not is_new and cached is not None:
        response.status_code = status or 201
        return DeploymentEntry(**cached)
    entry = deployment_service.create_deployment(request)
    idempotency.complete(
        x_idempotency_key, endpoint, request, 201, entry
    )
    return entry


@router.post("/reconcile-all", response_model=list[DeploymentReconcileResult])
def reconcile_all_deployments_endpoint() -> list[DeploymentReconcileResult]:
    """running/pending 배포 전체에 reconcile을 적용한다."""
    return deployment_service.reconcile_all_active()


@router.get("/{deployment_id}", response_model=DeploymentEntry)
def get_deployment_endpoint(deployment_id: str) -> DeploymentEntry:
    """배포 단건 조회"""
    return deployment_service.get_deployment(deployment_id)


@router.post("/{deployment_id}/stop", response_model=DeploymentEntry)
def stop_deployment_endpoint(deployment_id: str) -> DeploymentEntry:
    """배포 정지/제거"""
    return deployment_service.stop_deployment(deployment_id)


@router.post("/{deployment_id}/rollback", response_model=DeploymentEntry)
def rollback_deployment_endpoint(deployment_id: str) -> DeploymentEntry:
    """이전 배포로 1-click 롤백"""
    return deployment_service.rollback_deployment(deployment_id)


@router.post("/{deployment_id}/reconcile", response_model=DeploymentReconcileResult)
def reconcile_deployment_endpoint(deployment_id: str) -> DeploymentReconcileResult:
    """저장된 배포 상태와 Docker 런타임 상태를 대조·정정한다."""
    return deployment_service.reconcile_deployment(deployment_id)
