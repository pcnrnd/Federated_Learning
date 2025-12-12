"""컨테이너 관리 API 엔드포인트"""
from fastapi import APIRouter
from models.schemas import ContainerAction
from services.docker_service import get_docker_client

router = APIRouter(prefix="/api/containers", tags=["containers"])


@router.get("")
def list_containers(node_id: str, all: bool = True):
    """
    특정 노드의 컨테이너 목록 조회
    """
    client = get_docker_client(node_id)
    containers = client.containers.list(all=all)

    result = []
    for c in containers:
        # 포트 정보 간단 정리
        ports = []
        if c.ports:
            for k, v in c.ports.items():
                if v:
                    for m in v:
                        host = m.get("HostIp")
                        port = m.get("HostPort")
                        ports.append(f"{host}:{port}->{k}")
                else:
                    ports.append(k)

        result.append(
            {
                "id": c.short_id,
                "name": c.name,
                "image": ", ".join(c.image.tags) if c.image.tags else c.image.id,
                "status": c.status,
                "ports": ", ".join(ports),
            }
        )
    return result


@router.post("/start")
def start_container(action: ContainerAction):
    client = get_docker_client(action.node_id)
    container = client.containers.get(action.container_id)
    container.start()
    return {"ok": True}


@router.post("/stop")
def stop_container(action: ContainerAction):
    client = get_docker_client(action.node_id)
    container = client.containers.get(action.container_id)
    container.stop()
    return {"ok": True}


@router.post("/restart")
def restart_container(action: ContainerAction):
    client = get_docker_client(action.node_id)
    container = client.containers.get(action.container_id)
    container.restart()
    return {"ok": True}

