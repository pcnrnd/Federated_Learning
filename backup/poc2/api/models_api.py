"""모델 레지스트리 API 엔드포인트"""
from __future__ import annotations

from fastapi import APIRouter, Header, Response

from models.common_schemas import OkResponse
from models.packaging_schemas import ModelEntry, ModelRegisterRequest
from services import idempotency, model_registry

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=list[ModelEntry])
def list_models_endpoint() -> list[ModelEntry]:
    """등록된 모든 모델 버전 목록"""
    return model_registry.list_models()


@router.post("", response_model=ModelEntry, status_code=201)
def register_model_endpoint(
    payload: ModelRegisterRequest,
    response: Response,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> ModelEntry:
    """신규 모델 버전 등록 — X-Idempotency-Key 지원"""
    endpoint = "POST /api/models"
    is_new, cached, status = idempotency.begin(x_idempotency_key, endpoint, payload)
    if not is_new and cached is not None:
        response.status_code = status or 201
        return ModelEntry(**cached)
    entry = model_registry.register_model(payload)
    idempotency.complete(x_idempotency_key, endpoint, payload, 201, entry)
    return entry


@router.get("/{name}/versions", response_model=list[ModelEntry])
def list_versions_endpoint(name: str) -> list[ModelEntry]:
    """특정 모델의 버전 목록 (최신순)"""
    return model_registry.list_versions(name)


@router.get("/{name}/latest", response_model=ModelEntry)
def latest_endpoint(name: str) -> ModelEntry:
    """SemVer 최신 버전"""
    return model_registry.latest_version(name)


@router.get("/{name}/{version}", response_model=ModelEntry)
def get_model_endpoint(name: str, version: str) -> ModelEntry:
    """모델 버전 단건 조회"""
    return model_registry.get_model(name, version)


@router.delete("/{name}/{version}", response_model=OkResponse)
def delete_model_endpoint(name: str, version: str) -> OkResponse:
    """모델 버전 제거"""
    model_registry.delete_model(name, version)
    return OkResponse(ok=True)
