"""servers 저장소를 공유하는 실제 사일로 등록/조회."""
from __future__ import annotations

import threading

from fastapi import HTTPException

from config.server_manager import load_servers, save_servers
from models.silo_schemas import SiloRegisterRequest, SiloRegistration
from services import docker_service, silo_group_service

_lock = threading.RLock()


def list_silos() -> list[SiloRegistration]:
    return [
        SiloRegistration(
            silo_id=node_id,
            label=info.get("label", node_id),
            base_url=info["base_url"],
            collect_interval_seconds=info.get("collect_interval_seconds", 15),
        )
        for node_id, info in sorted(load_servers().items())
        if node_id != "main" and info.get("role") != "central"
    ]


def register_silo(request: SiloRegisterRequest) -> SiloRegistration:
    with _lock:
        servers = load_servers()
        if request.silo_id in servers or request.silo_id == "main":
            raise HTTPException(status_code=409, detail="이미 등록된 사일로 식별자입니다")
        servers[request.silo_id] = {
            "base_url": request.base_url,
            "label": request.label,
            "collect_interval_seconds": request.collect_interval_seconds,
            "role": "client",
            "type": "remote",
        }
        save_servers(servers)
        docker_service.refresh_docker_hosts()
    return SiloRegistration(**request.model_dump())


def delete_silo(silo_id: str) -> None:
    with _lock:
        servers = load_servers()
        if silo_id == "main" or servers.get(silo_id, {}).get("role") == "central":
            raise HTTPException(status_code=409, detail="중앙 서버는 해제할 수 없습니다")
        if silo_id not in servers:
            raise HTTPException(status_code=404, detail="등록되지 않은 사일로입니다")
        references = [
            g.group_id for g in silo_group_service.list_groups()
            if silo_id in g.member_node_ids or silo_id == g.aggregator_node_id
        ]
        if references:
            raise HTTPException(status_code=409, detail=f"그룹에서 먼저 해제하세요: {references}")
        del servers[silo_id]
        save_servers(servers)
        docker_service.refresh_docker_hosts()
