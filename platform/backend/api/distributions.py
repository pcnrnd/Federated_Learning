"""공통 bin·출력 계보를 검증하는 신규 분포 API. legacy drift API는 보존한다."""
from fastapi import APIRouter

from models.distribution_schemas import DistributionBaselineRequest, DistributionConfigRequest, DistributionPolicyRequest
from services import distribution_service as service
from services import distribution_drift as drift
from models.retraining_schemas import RetrainCommand, RetrainConfigRequest
from services import retraining_config, retraining_service

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


@router.post("/policies")
def put_policy(request: DistributionPolicyRequest) -> dict:
    return drift.put_policy(request.model_dump())


@router.get("/drift")
def get_drift() -> dict:
    return drift.overview()


@router.get("/events")
def get_events(config_id: str, node_id: str) -> list[dict]:
    return drift.events(config_id, node_id)


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: str) -> dict:
    return drift.ack(alert_id)


@router.get("/retraining")
def retraining_overview() -> dict:
    return retraining_service.overview()


@router.post("/retraining/configs")
def put_retraining_config(request: RetrainConfigRequest) -> dict:
    return retraining_config.put_config(request.model_dump())


@router.post("/retraining/events", status_code=202)
def create_retraining_event(request: RetrainCommand) -> dict:
    return retraining_service.create_manual(request.model_dump())


@router.get("/retraining/events/{identity}")
def get_retraining_event(identity: str) -> dict:
    return retraining_service.get_event(identity)


@router.post("/retraining/events/{identity}/retry")
def retry_retraining_event(identity: str) -> dict:
    return retraining_service.retry(identity)
