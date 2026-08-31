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


def _index_topology(exclude_group_id: str | None) -> tuple[dict[str, str], ...]:
    """기존 그룹들을 (클러스터 멤버 / 클러스터 집계자 / 루트 멤버) 소속 맵으로 색인한다.

    `exclude_group_id`는 수정 시 자기 자신의 기존 멤버십과 충돌하지 않도록 제외한다.
    """
    cluster_member_of: dict[str, str] = {}
    cluster_aggregator_of: dict[str, str] = {}
    root_member_of: dict[str, str] = {}
    for group in list_groups():
        if group.group_id == exclude_group_id:
            continue
        if group.aggregator_node_id is None:
            for node_id in group.member_node_ids:
                root_member_of[node_id] = group.group_id
            continue
        cluster_aggregator_of[group.aggregator_node_id] = group.group_id
        for node_id in group.member_node_ids:
            cluster_member_of[node_id] = group.group_id
    return cluster_member_of, cluster_aggregator_of, root_member_of


def _validate_topology(request: SiloGroupRequest, *, exclude_group_id: str | None) -> None:
    """그룹 토폴로지 검증 (HFL 설계 스펙 §4.2 — 계층 불변식을 한 지점에서 강제).

    루트(비클러스터) 그룹과 엣지 클러스터 **양쪽 모두**를 검사하므로 생성 순서에
    무관하게 같은 토폴로지가 같은 판정을 받는다.

    ① 집계자는 자기 클러스터의 멤버를 겸할 수 없다.
    ② 2단 제한 — 타 클러스터의 멤버는 집계자가 될 수 없고, 타 클러스터의 집계자를
       멤버로 받을 수도 없다 (양방향).
    ③ 한 노드는 최대 1개 클러스터의 멤버.
    ④ 한 노드는 최대 1개 클러스터의 집계자.
    ⑤ 클러스터 하위 노드와 루트 그룹 멤버는 상호 배타 — 겸하면 집계자의 대리 제출과
       본인의 직접 제출로 **표본이 이중 계상**된다 (스펙 §5의 전제 불변식).
       단 **집계자는 루트 그룹 멤버여야 정상**이므로 집계자에게는 적용하지 않는다.
    """
    aggregator = request.aggregator_node_id
    members = request.member_node_ids
    cluster_member_of, cluster_aggregator_of, root_member_of = _index_topology(
        exclude_group_id
    )

    if aggregator is None:
        # 루트 그룹 — ⑤ 역방향. 클러스터의 '집계자'는 루트 멤버여야 정상이라 막지 않는다.
        absorbed = [n for n in members if n in cluster_member_of]
        if absorbed:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"클러스터 하위 노드는 루트 그룹의 멤버가 될 수 없습니다"
                    f"(표본 이중 계상): {absorbed}"
                ),
            )
        return

    _validate_members([aggregator])

    if aggregator in members:
        raise HTTPException(
            status_code=400,
            detail=f"집계자 '{aggregator}'는 자기 클러스터의 멤버가 될 수 없습니다",
        )

    if aggregator in cluster_member_of:
        raise HTTPException(
            status_code=400,
            detail=(
                f"2단 제한 위반: '{aggregator}'는 클러스터 "
                f"'{cluster_member_of[aggregator]}'의 멤버이므로 집계자가 될 수 없습니다"
            ),
        )

    if aggregator in cluster_aggregator_of:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{aggregator}'는 이미 클러스터 "
                f"'{cluster_aggregator_of[aggregator]}'의 집계자입니다"
            ),
        )

    nested = [n for n in members if n in cluster_aggregator_of]
    if nested:
        raise HTTPException(
            status_code=400,
            detail=f"2단 제한 위반: 다른 클러스터의 집계자를 하위 멤버로 둘 수 없습니다: {nested}",
        )

    duplicated = [n for n in members if n in cluster_member_of]
    if duplicated:
        raise HTTPException(
            status_code=400,
            detail=f"이미 다른 클러스터에 소속된 노드: {duplicated}",
        )

    absorbed = [n for n in members if n in root_member_of]
    if absorbed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"루트 그룹 멤버는 클러스터 하위 노드가 될 수 없습니다"
                f"(표본 이중 계상): {absorbed}"
            ),
        )


def list_groups() -> list[SiloGroup]:
    return [SiloGroup(**v) for v in load_silo_groups().values()]


def get_cluster_by_aggregator(node_id: str) -> SiloGroup | None:
    """해당 노드가 집계자인 엣지 클러스터를 반환 (없으면 None)."""
    for group in list_groups():
        if group.aggregator_node_id == node_id:
            return group
    return None


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
    _validate_topology(request, exclude_group_id=None)

    now = _now_iso()
    group = SiloGroup(
        group_id=request.group_id,
        description=request.description,
        member_node_ids=list(request.member_node_ids),
        tags=list(request.tags),
        metadata=dict(request.metadata),
        created_at=now,
        updated_at=now,
        aggregator_node_id=request.aggregator_node_id,
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
    _validate_topology(request, exclude_group_id=group_id)

    existing = SiloGroup(**groups[group_id])
    updated = existing.model_copy(
        update={
            "description": request.description,
            "member_node_ids": list(request.member_node_ids),
            "tags": list(request.tags),
            "metadata": dict(request.metadata),
            "updated_at": _now_iso(),
            "aggregator_node_id": request.aggregator_node_id,
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
