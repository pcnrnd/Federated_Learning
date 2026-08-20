"""연합컴퓨팅 플랫폼 FastAPI 진입점

P0/P1 작업물 (모델 패키징/배포, 모니터링, 사일로 링크/파라미터 수집,
Batch Scheduling, 리소스 모니터링) 라우터를 통합한다.

실행:
    cd app
    uvicorn main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api import (
    ab_tests,
    cleaning_jobs,
    cleaning_recipes,
    dashboard,
    deployments,
    lineage,
    models_api,
    monitoring,
    packaging,
    resources,
    shadow,
    silo_groups,
    training_jobs,
    training_rounds,
    visualizations,
)
from api.exception_handlers import register_exception_handlers
from config import settings
from services.round_scheduler import get_scheduler


@asynccontextmanager
async def _lifespan(app: FastAPI):
    scheduler = get_scheduler()
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(title="Federated Computing Platform", lifespan=_lifespan)
register_exception_handlers(app)

# React 개발 및 API 연동용 CORS 활성화
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _requires_api_key(path: str) -> bool:
    return bool(settings.API_KEY) and (path == "/api" or path.startswith("/api/"))


def _api_key_is_valid(path: str, provided_key: str | None) -> bool:
    if not _requires_api_key(path):
        return True
    return provided_key == settings.API_KEY


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Protect API routes when FED_API_KEY is configured."""
    if not _api_key_is_valid(
        request.url.path,
        request.headers.get(settings.API_KEY_HEADER),
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "유효한 API Key가 필요합니다", "code": "unauthorized"},
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return await call_next(request)

# 정적 파일 + 템플릿 (UI 대시보드)
_BASE_DIR = Path(__file__).parent
_STATIC_DIR = _BASE_DIR / "static"
_TEMPLATES_DIR = _BASE_DIR / "templates"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    
# React 빌드 assets 디렉토리 동적 마운트
_REACT_DIST_DIR = _STATIC_DIR / "dist"
if (_REACT_DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_REACT_DIST_DIR / "assets")), name="assets")

_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR)) if _TEMPLATES_DIR.exists() else None

# 모델 패키징/배포 (P0 #1)
app.include_router(models_api.router)
app.include_router(packaging.router)
app.include_router(deployments.router)

# 모델 모니터링 (P0 #2)
app.include_router(monitoring.router)

# 사일로 링크 + 파라미터 수집 (P1)
app.include_router(silo_groups.router)
app.include_router(training_rounds.router)

# Batch Scheduling 자동화 (P1)
app.include_router(training_jobs.router)

# 리소스 모니터링 (P1)
app.include_router(resources.router)

# 모델 유지관리 — lineage / 섀도우 배포 / A·B 테스트 (P1)
app.include_router(lineage.router)
app.include_router(shadow.router)
app.include_router(ab_tests.router)

# 데이터 정제 (P1)
app.include_router(cleaning_recipes.router)
app.include_router(cleaning_jobs.router)

# 사일로 데이터 시각화 (P2) — 공인인증 KPI (5종 × 6 사일로)
app.include_router(visualizations.router)

# 비동기 I/O — 통합 대시보드 (P2)
app.include_router(dashboard.router)


@app.get("/")
def index() -> dict[str, str]:
    return {"service": "Federated Computing Platform", "status": "ok"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """프로세스 생존 여부 확인용 경량 probe."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response) -> dict[str, object]:
    """운영/데모 실행 전 필수 구성요소가 준비됐는지 확인한다."""
    scheduler = get_scheduler()
    config_dir = settings.CONFIG_DIR
    checks = {
        "config_dir_exists": config_dir.exists(),
        "config_dir_writable": config_dir.exists()
        and config_dir.is_dir()
        and os.access(config_dir, os.W_OK),
        "scheduler_running": scheduler.running,
        "templates_available": _templates is not None,
    }
    ready = all(checks.values())
    if not ready:
        response.status_code = 503
    return {"status": "ready" if ready else "not_ready", "checks": checks}


@app.get("/dashboard")
def dashboard_ui(request: Request):
    """대시보드 UI — React SPA 빌드본이 존재하면 우선 반환하고 없으면 기존 바닐라 폴백"""
    react_index = _BASE_DIR / "static" / "dist" / "index.html"
    if react_index.exists():
        return FileResponse(str(react_index))
    if _templates is None:
        return {"error": "templates 디렉토리 없음"}
    return _templates.TemplateResponse(request, "dashboard.html")
