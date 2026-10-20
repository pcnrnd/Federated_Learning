"""공통 bin·출력 계보를 검증하는 신규 분포 API. legacy drift API는 보존한다."""
from fastapi import APIRouter

from models.distribution_schemas import DistributionBaselineRequest, DistributionConfigRequest
from services import distribution_service as service

router = APIRouter(prefix="/api/monitoring/distributions", tags=["분포 관측"])


@router.post("/configs", status_code=201)
def create_config(request: DistributionConfigRequest) -> dict:
    return service.create_config(request.model_dump())


@router.get("/configs")
def list_configs(node_id: str | None = None) -> list[dict]:
    return service.list_configs(node_id)


@router.post("/reports")
def accept_report(request: dict) -> dict:
    return service.accept_report(request)


@router.get("/reports/{report_id}")
def get_report(report_id: str) -> dict:
    return service.get_report(report_id)


@router.get("/current")
def get_current(config_id: str, node_id: str) -> dict:
    return service.get_current(config_id, node_id)


@router.post("/baselines")
def select_baseline(request: DistributionBaselineRequest) -> dict:
    return service.select_baseline(request.report_id)


@router.get("/baselines")
def get_baseline(config_id: str, node_id: str) -> dict:
    return service.get_current(config_id, node_id, baseline=True)


@router.get("/baselines/{baseline_id}")
def get_baseline_history(baseline_id: str) -> dict:
    return service.get_baseline(baseline_id)
