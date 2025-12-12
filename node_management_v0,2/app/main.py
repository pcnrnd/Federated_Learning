"""FastAPI 애플리케이션 진입점"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from api import nodes, containers
from services.docker_service import get_docker_hosts

app = FastAPI(title="FL Container Dashboard")

# 정적 파일 및 템플릿 설정
BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# API 라우터 등록
app.include_router(nodes.router)
app.include_router(containers.router)


@app.get("/")
def index(request: Request):
    """초기 페이지 렌더링"""
    hosts = get_docker_hosts()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "nodes": [
                {"id": node_id, "label": info["label"]}
                for node_id, info in hosts.items()
            ],
        },
    )
