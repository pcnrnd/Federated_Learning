"""사일로 그룹 관리 서비스"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from config.federated_manager import load_silo_groups, save_silo_groups
from config.server_manager import load_servers
from models.federated_schemas import SiloGroup, SiloGroupRequest, SiloMemberInfo

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_members(member_node_ids: list[str]) -> None:
    servers = load_servers()
    unknown = [n for n in member_node_ids if n not in servers]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"등록되지 않은 노드: {unknown}",
        )


def list_groups() -> list[SiloGroup]:
    return [SiloGroup(**v) for v in load_silo_groups().values()]


def get_group(group_id: str) -> SiloGroup:
    groups = load_silo_groups()
    if group_id not in groups:
        raise HTTPException(status_code=404, detail=f"그룹 '{group_id}'을 찾을 수 없습니다")
    return SiloGroup(**groups[group_id])


def create_group(request: SiloGroupRequest) -> SiloGroup:
    groups = load_silo_groups()
    if request.group_id in groups:
        raise HTTPException(
            status_code=409,
            detail=f"그룹 '{request.group_id}'은 이미 존재합니다",
        )
    _validate_members(request.member_node_ids)

    now = _now_iso()
    group = SiloGroup(
        group_id=request.group_id,
        description=request.description,
        member_node_ids=list(request.member_node_ids),
        tags=list(request.tags),
        metadata=dict(request.metadata),
        created_at=now,
        updated_at=now,
    )
    groups[request.group_id] = group.model_dump()
    save_silo_groups(groups)
    logger.info("그룹 생성: %s (members=%s)", request.group_id, request.member_node_ids)
    return group


def update_group(group_id: str, request: SiloGroupRequest) -> SiloGroup:
    groups = load_silo_groups()
    if group_id not in groups:
        raise HTTPException(status_code=404, detail=f"그룹 '{group_id}'을 찾을 수 없습니다")
    _validate_members(request.member_node_ids)

    existing = SiloGroup(**groups[group_id])
    updated = existing.model_copy(
        update={
            "description": request.description,
            "member_node_ids": list(request.member_node_ids),
            "tags": list(request.tags),
            "metadata": dict(request.metadata),
            "updated_at": _now_iso(),
        }
    )
    groups[group_id] = updated.model_dump()
    save_silo_groups(groups)
    return updated


def delete_group(group_id: str) -> None:
    groups = load_silo_groups()
    if group_id not in groups:
        raise HTTPException(status_code=404, detail=f"그룹 '{group_id}'을 찾을 수 없습니다")
    del groups[group_id]
    save_silo_groups(groups)
    logger.info("그룹 삭제: %s", group_id)


def list_members(group_id: str) -> list[SiloMemberInfo]:
    """그룹의 멤버 노드를 servers.yaml과 join 해서 반환"""
    group = get_group(group_id)
    servers = load_servers()
    members: list[SiloMemberInfo] = []
    for node_id in group.member_node_ids:
        info = servers.get(node_id, {})
        members.append(
            SiloMemberInfo(
                node_id=node_id,
                label=info.get("label", node_id),
                base_url=info.get("base_url"),
                role=info.get("role"),
                in_servers_yaml=node_id in servers,
            )
        )
    return members
