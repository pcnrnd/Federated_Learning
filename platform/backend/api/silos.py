"""사일로 등록 API. 실측 유무와 무관하게 등록된 노드를 조회한다."""
from fastapi import APIRouter, HTTPException

from models.common_schemas import OkResponse
from models.silo_schemas import SiloRegisterRequest, SiloRegistration
from services import silo_registration_service

router = APIRouter(prefix="/api/silos", tags=["silos"])


@router.get("", response_model=list[SiloRegistration])
def list_silos() -> list[SiloRegistration]:
    return silo_registration_service.list_silos()


@router.post("", response_model=SiloRegistration, status_code=201)
def register_silo(request: SiloRegisterRequest) -> SiloRegistration:
    return silo_registration_service.register_silo(request)


@router.get("/{silo_id}", response_model=SiloRegistration)
def get_silo(silo_id: str) -> SiloRegistration:
    for silo in silo_registration_service.list_silos():
        if silo.silo_id == silo_id:
            return silo
    raise HTTPException(status_code=404, detail="등록되지 않은 사일로입니다")


@router.delete("/{silo_id}", response_model=OkResponse)
def delete_silo(silo_id: str) -> OkResponse:
    silo_registration_service.delete_silo(silo_id)
    return OkResponse()
