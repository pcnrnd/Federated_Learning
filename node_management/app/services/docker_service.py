"""Docker 클라이언트 관리 서비스"""
import docker
from fastapi import HTTPException
from config.server_manager import load_servers

# 전역 상태 (기존 DOCKER_HOSTS 대체)
_docker_hosts = {}


def refresh_docker_hosts():
    """DOCKER_HOSTS를 최신 설정으로 갱신 (중복 코드 제거)"""
    global _docker_hosts
    latest_servers = load_servers()
    _docker_hosts.clear()
    _docker_hosts.update(latest_servers)
    return _docker_hosts


def get_docker_hosts():
    """현재 Docker 호스트 목록 반환"""
    if not _docker_hosts:
        refresh_docker_hosts()
    return _docker_hosts


def get_docker_client(node_id: str) -> docker.DockerClient:
    """특정 노드의 Docker 클라이언트 반환"""
    hosts = get_docker_hosts()
    if node_id not in hosts:
        raise HTTPException(status_code=404, detail="Unknown node")

    cfg = hosts[node_id]
    return docker.DockerClient(base_url=cfg["base_url"])

