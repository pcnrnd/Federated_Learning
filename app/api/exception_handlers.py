"""FastAPI 전역 예외 핸들러 — 일관된 ErrorResponse 형식"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from models.common_schemas import ErrorResponse

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """앱에 공통 예외 핸들러를 등록한다."""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        """HTTPException → ErrorResponse JSON"""
        detail = exc.detail
        if isinstance(detail, list):
            # Pydantic/FastAPI 검증 에러 리스트
            msg = "; ".join(
                str(d.get("msg", d)) if isinstance(d, dict) else str(d)
                for d in detail
            )
            field = None
            if detail and isinstance(detail[0], dict):
                loc = detail[0].get("loc", ())
                if loc:
                    field = ".".join(str(x) for x in loc if x != "body")
            body = ErrorResponse(detail=msg, code=f"http_{exc.status_code}", field=field)
        elif isinstance(detail, dict):
            body = ErrorResponse(
                detail=str(detail.get("detail", detail)),
                code=detail.get("code"),
                field=detail.get("field"),
            )
        else:
            body = ErrorResponse(detail=str(detail), code=f"http_{exc.status_code}")
        return JSONResponse(
            status_code=exc.status_code,
            content=body.model_dump(exclude_none=True),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """요청 본문/쿼리 검증 실패"""
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = first.get("loc", ())
        field = ".".join(str(x) for x in loc if x not in ("body",)) or None
        msg = first.get("msg", "요청 검증 실패")
        body = ErrorResponse(detail=str(msg), code="validation_error", field=field)
        return JSONResponse(status_code=422, content=body.model_dump(exclude_none=True))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """예상치 못한 서버 오류"""
        logger.exception("처리되지 않은 예외: %s %s", request.method, request.url.path)
        body = ErrorResponse(detail="내부 서버 오류", code="internal_error")
        return JSONResponse(status_code=500, content=body.model_dump(exclude_none=True))
