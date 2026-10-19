"""모델 레지스트리 API 엔드포인트"""
from __future__ import annotations

from fastapi import APIRouter, Header, Response

from models.common_schemas import OkResponse
from models.packaging_schemas import (
    ModelEntry, ModelIdentityRequest, ModelRegisterRequest, RidgeIdentityPredictRequest,
    RidgePredictRequest, TrainingModelRegisterRequest,
)
from services import idempotency, model_registry, training_model_service

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


@router.post("/archive", response_model=ModelEntry)
def archive_identity(payload: ModelIdentityRequest):
    # JSON 식별자는 모델 이름의 slash/공백/Unicode를 경로 구분자로 바꾸지 않는다.
    return model_registry.archive_model(payload.name, payload.version)


@router.delete("", response_model=OkResponse)
def delete_identity(payload: ModelIdentityRequest):
    model_registry.delete_model(payload.name, payload.version)
    return OkResponse(ok=True)


@router.post("/predict")
def predict_identity(payload: RidgeIdentityPredictRequest):
    return model_registry.predict_model(payload.name, payload.version, payload.inputs)


@router.get("/{name}/versions", response_model=list[ModelEntry])
def list_versions_endpoint(name: str) -> list[ModelEntry]:
    """특정 모델의 버전 목록 (최신순)"""
    return model_registry.list_versions(name)


@router.post("/from-training", response_model=ModelEntry, status_code=201)
def register_training_result(payload: TrainingModelRegisterRequest):
    return training_model_service.register_completed_result(payload.round_id, version=payload.version)


@router.get("/training-results")
def registration_states():
    return training_model_service.list_registrations()


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


@router.post("/{name}/{version}/archive", response_model=ModelEntry)
def archive_model_endpoint(name: str, version: str):
    return model_registry.archive_model(name, version)


@router.post("/{name}/{version}/predict")
def predict_model_endpoint(name: str, version: str, payload: RidgePredictRequest):
    return model_registry.predict_model(name, version, payload.inputs)
