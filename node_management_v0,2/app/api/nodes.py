"""서버 관리 API 엔드포인트"""
from fastapi import APIRouter, HTTPException
from datetime import datetime
import docker
from models.schemas import ServerConfig
from services.docker_service import get_docker_client, get_docker_hosts, refresh_docker_hosts
from config.server_manager import load_servers, save_servers

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


@router.get("")
def list_nodes():
    """서버 목록 조회"""
    refresh_docker_hosts()
    hosts = get_docker_hosts()
    return [
        {"id": node_id, "label": info.get("label", node_id)}
        for node_id, info in hosts.items()
    ]


@router.get("/status")
def get_nodes_status():
    """모든 서버의 연결 상태 확인"""
    try:
        # 최신 설정 로드 (전체 교체하여 삭제된 서버도 제거)
        try:
            refresh_docker_hosts()
        except Exception as e:
            print(f"서버 설정 로드 오류: {e}")
            # 기존 설정 유지하거나 기본값 사용
            hosts = get_docker_hosts()
            if not hosts:
                refresh_docker_hosts()
        
        hosts = get_docker_hosts()
        status_list = []
        for node_id, info in hosts.items():
            try:
                client = docker.DockerClient(base_url=info["base_url"])
                client.ping()  # 연결 테스트
                status_list.append({
                    "id": node_id,
                    "label": info.get("label", node_id),
                    "status": "online",
                    "type": info.get("type", "unknown"),
                    "role": info.get("role", "client"),
                    "base_url": info.get("base_url", ""),
                    "last_check": datetime.now().isoformat()
                })
            except Exception as e:
                status_list.append({
                    "id": node_id,
                    "label": info.get("label", node_id),
                    "status": "offline",
                    "type": info.get("type", "unknown"),
                    "role": info.get("role", "client"),
                    "base_url": info.get("base_url", ""),
                    "error": str(e),
                    "last_check": datetime.now().isoformat()
                })
        return status_list
    except Exception as e:
        # 전체 함수 레벨 에러 처리
        print(f"서버 상태 조회 오류: {e}")
        raise HTTPException(status_code=500, detail=f"서버 상태 조회 실패: {str(e)}")


@router.get("/{node_id}")
def get_node(node_id: str):
    """서버 상세 정보 조회"""
    refresh_docker_hosts()
    hosts = get_docker_hosts()
    
    if node_id not in hosts:
        raise HTTPException(status_code=404, detail="서버를 찾을 수 없습니다")
    
    info = hosts[node_id]
    return {
        "id": node_id,
        "label": info.get("label", node_id),
        "base_url": info.get("base_url", ""),
        "type": info.get("type", "remote"),
        "role": info.get("role", "client"),
        "tls": info.get("tls", False)
    }


@router.post("")
def add_node(server: ServerConfig):
    """서버 추가"""
    servers = load_servers()
    
    # ID 중복 확인
    if server.id in servers:
        raise HTTPException(status_code=400, detail=f"서버 ID '{server.id}'가 이미 존재합니다")
    
    # 서버 정보 추가 - 새로 추가하는 서버는 항상 클라이언트 서버
    servers[server.id] = {
        "base_url": server.base_url,
        "label": server.label,
        "type": "remote",  # 클라이언트 서버는 항상 원격
        "role": "client",  # 새로 추가하는 서버는 항상 클라이언트
        "tls": server.tls
    }
    
    save_servers(servers)
    refresh_docker_hosts()
    
    return {"ok": True, "message": f"서버 '{server.label}'가 추가되었습니다"}


@router.put("/{node_id}")
def update_node(node_id: str, server: ServerConfig):
    """서버 수정"""
    servers = load_servers()
    
    if node_id not in servers:
        raise HTTPException(status_code=404, detail="서버를 찾을 수 없습니다")
    
    # 서버 정보 업데이트 - 기존 역할 유지 (중앙 서버는 고정, 클라이언트는 유지)
    existing_role = servers[node_id].get("role", "client")
    if node_id == "main":
        # 중앙 서버는 역할과 타입 고정
        final_role = "central"
        final_type = "local"
    else:
        # 클라이언트 서버는 기존 역할 유지
        final_role = existing_role
        final_type = "remote"
    
    servers[node_id] = {
        "base_url": server.base_url,
        "label": server.label,
        "type": final_type,
        "role": final_role,
        "tls": server.tls
    }
    
    # ID가 변경된 경우
    if server.id != node_id:
        if server.id in servers:
            raise HTTPException(status_code=400, detail=f"서버 ID '{server.id}'가 이미 존재합니다")
        servers[server.id] = servers.pop(node_id)
    
    save_servers(servers)
    refresh_docker_hosts()
    
    return {"ok": True, "message": f"서버 '{server.label}'가 수정되었습니다"}


@router.delete("/{node_id}")
def delete_node(node_id: str):
    """서버 삭제"""
    servers = load_servers()
    
    if node_id not in servers:
        raise HTTPException(status_code=404, detail="서버를 찾을 수 없습니다")
    
    # 중앙 서버는 삭제 불가
    if node_id == "main":
        raise HTTPException(status_code=400, detail="중앙 서버는 삭제할 수 없습니다")
    
    label = servers[node_id].get("label", node_id)
    del servers[node_id]
    
    save_servers(servers)
    refresh_docker_hosts()
    
    return {"ok": True, "message": f"서버 '{label}'가 삭제되었습니다"}


@router.post("/{node_id}/test")
def test_connection(node_id: str):
    """서버 연결 테스트"""
    refresh_docker_hosts()
    hosts = get_docker_hosts()
    
    if node_id not in hosts:
        raise HTTPException(status_code=404, detail="서버를 찾을 수 없습니다")
    
    info = hosts[node_id]
    try:
        client = docker.DockerClient(base_url=info["base_url"])
        client.ping()  # 연결 테스트
        
        # 추가 정보 가져오기
        version = client.version()
        return {
            "ok": True,
            "status": "online",
            "version": version.get("Version", "unknown"),
            "api_version": version.get("ApiVersion", "unknown")
        }
    except Exception as e:
        return {
            "ok": False,
            "status": "offline",
            "error": str(e)
        }

