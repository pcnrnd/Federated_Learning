"""사일로 그룹 API 엔드포인트"""
from __future__ import annotations

from fastapi import APIRouter, Header, Response

from models.common_schemas import OkResponse
from models.federated_schemas import SiloGroup, SiloGroupRequest, SiloMemberInfo
from services import idempotency, silo_group_service

router = APIRouter(prefix="/api/silo-groups", tags=["silo-groups"])


@router.get("", response_model=list[SiloGroup])
def list_groups_endpoint() -> list[SiloGroup]:
    return silo_group_service.list_groups()


@router.post("", response_model=SiloGroup, status_code=201)
def create_group_endpoint(
    request: SiloGroupRequest,
    response: Response,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> SiloGroup:
    """사일로 그룹 생성 — X-Idempotency-Key 지원"""
    endpoint = "POST /api/silo-groups"
    is_new, cached, status = idempotency.begin(x_idempotency_key, endpoint, request)
    if not is_new and cached is not None:
        response.status_code = status or 201
        return SiloGroup(**cached)
    group = silo_group_service.create_group(request)
    idempotency.complete(x_idempotency_key, endpoint, request, 201, group)
    return group


@router.get("/{group_id}", response_model=SiloGroup)
def get_group_endpoint(group_id: str) -> SiloGroup:
    return silo_group_service.get_group(group_id)


@router.put("/{group_id}", response_model=SiloGroup)
def update_group_endpoint(group_id: str, request: SiloGroupRequest) -> SiloGroup:
    return silo_group_service.update_group(group_id, request)


@router.delete("/{group_id}", response_model=OkResponse)
def delete_group_endpoint(group_id: str) -> OkResponse:
    silo_group_service.delete_group(group_id)
    return OkResponse(ok=True)


@router.get("/{group_id}/members", response_model=list[SiloMemberInfo])
def list_members_endpoint(group_id: str) -> list[SiloMemberInfo]:
    return silo_group_service.list_members(group_id)
