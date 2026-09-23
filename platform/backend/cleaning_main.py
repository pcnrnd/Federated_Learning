"""데이터 정제 서비스 단독 실행 진입점

통합 플랫폼(main.py) 없이 정제 레시피·정제 잡 API만 기동한다.
잡 생성은 사일로 그룹 멤버를 샤드로 배정하므로 사일로 그룹 API를 함께 싣는다
(그룹 멤버 노드는 CONFIG_DIR 의 servers.yaml 에 등록돼 있어야 한다).
사일로 측은 silo_sdk.cleaning 으로 레시피를 받아 로컬 실행 후 통계만 보고한다.

실행 (platform/backend 에서):
    python cleaning_main.py --host 0.0.0.0 --port 8010
    # 또는
    uvicorn cleaning_main:app --host 0.0.0.0 --port 8010
"""

from __future__ import annotations

import argparse
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api import cleaning_jobs, cleaning_recipes, silo_groups
from api.exception_handlers import register_exception_handlers
from config import settings

logger = logging.getLogger(__name__)

app = FastAPI(title="Federated Data Cleaning Service")
register_exception_handlers(app)


# ponytail: main.py 의 API Key 미들웨어와 같은 규칙을 복제 — 세 번째 진입점이 생기면 공용 모듈로 추출
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """FED_API_KEY 가 설정되면 /api/* 에 X-FED-API-Key 헤더를 요구한다."""
    path = request.url.path
    protected = bool(settings.API_KEY) and (path == "/api" or path.startswith("/api/"))
    if protected and request.headers.get(settings.API_KEY_HEADER) != settings.API_KEY:
        return JSONResponse(
            status_code=401,
            content={"detail": "유효한 API Key가 필요합니다", "code": "unauthorized"},
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return await call_next(request)


app.include_router(cleaning_recipes.router)
app.include_router(cleaning_jobs.router)
app.include_router(silo_groups.router)


@app.get("/")
def index() -> dict[str, str]:
    return {"service": "Federated Data Cleaning Service", "status": "ok"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """프로세스 생존 여부 확인용 경량 probe."""
    return {"status": "ok"}


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="데이터 정제 서비스 단독 실행")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args(argv)
    logger.info(
        "정제 서비스 기동: %s:%d (CONFIG_DIR=%s)",
        args.host,
        args.port,
        settings.CONFIG_DIR,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
