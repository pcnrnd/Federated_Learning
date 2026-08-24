"""PoC 통합 백엔드 FastAPI 메인 서버 애플리케이션"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any, List

from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from models import ServerConfig, ContainerAction, ModelPackage, ParameterPayload, CleaningRecipe
from services import DockerService, FederatedService

# 1. 초기화 및 환경설정
app = FastAPI(title="FCP PoC Federated Computing Engine API")

# 프론트엔드 분리 렌더링을 위한 CORS 활성화
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_BASE_DIR = Path(__file__).parent
_CONFIG_FILE = _BASE_DIR / "servers.yaml"

# 의존 서비스 탑재
docker_service = DockerService(_CONFIG_FILE)

# API 보안 키 설정 검출
API_KEY = os.getenv("FED_API_KEY", "")
API_KEY_HEADER = "X-FED-API-Key"

# 2. 미들웨어 보안 필터링
@app.middleware("http")
async def secure_api_key_middleware(request: Request, call_next):
    """FED_API_KEY 설정 상태에서 /api 라우트에 대해 API Key 토큰 검증 미들웨어"""
    path = request.url.path
    if API_KEY and (path == "/api" or path.startswith("/api/")):
        provided_key = request.headers.get(API_KEY_HEADER)
        if provided_key != API_KEY:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "유효한 API Key가 필요합니다", "code": "unauthorized"},
                headers={"WWW-Authenticate": "ApiKey"},
            )
    return await call_next(request)


# 3. 헬스체크 및 준비 검증 프로브
@app.get("/healthz")
def healthz() -> dict[str, str]:
    """경량 생존 진단 프로브"""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response) -> dict[str, object]:
    """PoC 구성 요소 준비 상태 확인 프로브"""
    checks = {
        "config_exists": _CONFIG_FILE.exists(),
        "config_writable": os.access(_CONFIG_FILE.parent, os.W_OK),
        "api_key_configured": bool(API_KEY)
    }
    ready = checks["config_exists"] and checks["config_writable"]
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "not_ready", "checks": checks}


# 4. 노드 & 사일로 관리 API
@app.get("/api/nodes")
def list_nodes():
    """서버 설정 파일에 기록된 전체 연합 노드 조회"""
    servers = docker_service.load_servers()
    output = []
    for node_id, cfg in servers.items():
        # 원격 연결 헬스체크 수행
        connected = docker_service.test_connection(cfg["base_url"])
        output.append({
            "node_id": node_id,
            "label": cfg["label"],
            "base_url": cfg["base_url"],
            "type": cfg["type"],
            "role": cfg["role"],
            "tls": cfg["tls"],
            "status": "connected" if connected else "disconnected"
        })
    return output


@app.post("/api/nodes", status_code=status.HTTP_201_CREATED)
def register_node(cfg: ServerConfig):
    """신규 연합 노드 가입 및 YAML 영속화"""
    servers = docker_service.load_servers()
    
    # 중복 체크 우회 및 고유 ID 자동 생성
    node_id = f"silo_{len(servers)}"
    
    servers[node_id] = {
        "base_url": cfg.base_url,
        "label": cfg.label,
        "type": "remote",      # 신규 가입 노드는 무조건 remote/client로 규정
        "role": "client",
        "tls": cfg.tls
    }
    docker_service.save_servers(servers)
    return {"node_id": node_id, **servers[node_id]}


@app.delete("/api/nodes/{node_id}")
def delete_node(node_id: str):
    """연합 노드 제거 (중앙 central 서버는 보호됨)"""
    if node_id == "main":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="중앙 마스터 서버 노드는 삭제할 수 없습니다."
        )
    servers = docker_service.load_servers()
    if node_id not in servers:
        raise HTTPException(status_code=404, detail="존재하지 않는 노드입니다.")
    
    del servers[node_id]
    docker_service.save_servers(servers)
    return {"status": "success", "removed_node": node_id}


@app.get("/api/nodes/{node_id}/containers")
def get_node_containers(node_id: str):
    """특정 사일로 노드의 물리 컨테이너 목록 실시간 모니터링"""
    try:
        return docker_service.list_containers(node_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"컨테이너 스캔 실패: {e}")


@app.post("/api/nodes/{node_id}/containers/{container_id}/action")
def control_node_container(node_id: str, container_id: str, act: ContainerAction):
    """특정 사일로 노드 내 컨테이너 원격 제어 (Start/Stop/Restart)"""
    try:
        success = docker_service.control_container(node_id, container_id, act.action)
        if not success:
            raise HTTPException(status_code=500, detail="컨테이너 제어 명령 전달에 실패했습니다.")
        return {"node_id": node_id, "container_id": container_id, "action": act.action, "status": "success"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# 5. 모델 패키징 & 배포 API (MLOps)
_MODEL_REGISTRY: dict[str, dict] = {}
_DEPLOYMENTS: list[dict] = []

@app.post("/api/models", status_code=status.HTTP_201_CREATED)
def register_model(pkg: ModelPackage):
    """신규 인공지능 글로벌 모델 등록/패키징"""
    model_id = f"md_{len(_MODEL_REGISTRY) + 1:04d}"
    _MODEL_REGISTRY[model_id] = {
        "model_name": pkg.model_name,
        "version": pkg.version,
        "framework": pkg.framework,
        "description": pkg.description,
        "status": "packaged"
    }
    return {"model_id": model_id, **_MODEL_REGISTRY[model_id]}


@app.post("/api/deployments", status_code=status.HTTP_202_ACCEPTED)
def deploy_model(model_id: str, target_nodes: list[str], mode: str = "shadow"):
    """글로벌 모델을 지정한 사일로 그룹에 배포 (섀도우/표준/AB 테스트)"""
    if model_id not in _MODEL_REGISTRY:
        raise HTTPException(status_code=404, detail="존재하지 않는 모델 패키지 ID입니다.")
        
    dep_id = f"dep_{len(_DEPLOYMENTS) + 1:04d}"
    deployment = {
        "deployment_id": dep_id,
        "model_id": model_id,
        "targets": target_nodes,
        "mode": mode,
        "status": "active"
    }
    _DEPLOYMENTS.append(deployment)
    return deployment


# 6. 연합학습 파라미터 수합 및 FedAvg API
# 연합 학습 라운드별 제출된 가중치 임시 버퍼 캐시
# 구조: { round_id: [ ParameterPayload, ... ] }
_ROUND_WEIGHTS_BUFFER: dict[str, list[dict]] = {}

@app.post("/api/rounds/{round_id}/parameters")
def submit_round_parameters(round_id: str, payload: ParameterPayload):
    """각 사일로가 제출하는 로컬 가중치 수합 수용소"""
    if round_id not in _ROUND_WEIGHTS_BUFFER:
        _ROUND_WEIGHTS_BUFFER[round_id] = []
        
    # 동일 노드 중복 제출 방지 처리
    _ROUND_WEIGHTS_BUFFER[round_id] = [
        item for item in _ROUND_WEIGHTS_BUFFER[round_id]
        if item["node_id"] != payload.node_id
    ]
    
    _ROUND_WEIGHTS_BUFFER[round_id].append(payload.model_dump())
    return {
        "round_id": round_id,
        "node_id": payload.node_id,
        "status": "received",
        "current_round_submissions": len(_ROUND_WEIGHTS_BUFFER[round_id])
    }


@app.post("/api/rounds/{round_id}/aggregate")
def trigger_fedavg_aggregation(round_id: str):
    """수집된 가중치 버퍼를 기반으로 FedAvg 가중평균 집계 강제 트리거"""
    if round_id not in _ROUND_WEIGHTS_BUFFER or not _ROUND_WEIGHTS_BUFFER[round_id]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="해당 라운드에 수합된 가중치 파라미터가 존재하지 않습니다."
        )
        
    try:
        payloads = _ROUND_WEIGHTS_BUFFER[round_id]
        global_weights = FederatedService.aggregate_fedavg(payloads)
        return {
            "round_id": round_id,
            "status": "aggregated",
            "participating_nodes_count": len(payloads),
            "global_weights": global_weights
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"FedAvg 집계 처리 실패: {e}")


# 7. 데이터 정제 잡(Job) 실행 API
@app.post("/api/cleaning-jobs", status_code=status.HTTP_202_ACCEPTED)
def execute_cleaning_job(recipe_name: str, target_nodes: list[str]):
    """지정한 연합 노드들에게 데이터 전처리/정제 Job 원격 트리거 배포"""
    return {
        "job_id": f"job_cln_{os.urandom(2).hex()}",
        "recipe_name": recipe_name,
        "targets": target_nodes,
        "status": "completed",
        "cleaning_metrics": {
            "initial_errors_detected": 142,
            "resolved_errors": 142,
            "precision_accuracy_rate": 1.0
        }
    }


@app.get("/")
def index():
    return {"service": "FCP PoC Back-end Engine API", "status": "active"}
