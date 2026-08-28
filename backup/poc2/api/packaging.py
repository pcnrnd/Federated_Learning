"""모델 패키징 API 엔드포인트"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from models.packaging_schemas import PackagingRequest, PackagingResult
from services import packaging_service

router = APIRouter(prefix="/api/packaging", tags=["packaging"])


@router.post("/build", response_model=PackagingResult)
def build_endpoint(request: PackagingRequest) -> PackagingResult:
    """등록된 모델을 Docker 이미지로 빌드"""
    return packaging_service.build_package(request)


@router.post("/dockerfile", response_class=PlainTextResponse)
def render_dockerfile_endpoint(request: PackagingRequest) -> str:
    """빌드 없이 Dockerfile만 렌더링 (드라이런)"""
    return packaging_service.render_dockerfile_only(request)
