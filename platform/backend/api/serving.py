"""고정 deployment endpoint를 실제로 소비하는 serving API. 요청 body를 기록하지 않는다."""
from fastapi import APIRouter, Query

from models.serving_schemas import ComparisonGate, ServingPredictRequest, ServingRouteRequest
from services import serving_requests, serving_routes, serving_store

router = APIRouter(prefix="/api/serving-routes", tags=["serving"])


@router.get("")
def list_routes():
    return serving_routes.list_routes()


@router.post("", status_code=201)
def create_route(request: ServingRouteRequest):
    return serving_routes.ensure_route(request.primary_deployment_id)


@router.post("/{route_id}/predict")
def predict(route_id: str, request: ServingPredictRequest):
    return serving_requests.predict(route_id, request)


@router.get("/{route_id}/comparison")
def comparison(route_id: str):
    return serving_requests.comparison(route_id)


@router.put("/{route_id}/gate")
def configure_gate(route_id: str, gate: ComparisonGate):
    return serving_routes.configure_gate(route_id, gate)


@router.post("/{route_id}/promote")
def promote(route_id: str):
    return serving_routes.promote(route_id)


@router.post("/{route_id}/rollback")
def rollback(route_id: str):
    return serving_routes.rollback(route_id)


@router.post("/{route_id}/close")
def close(route_id: str):
    return serving_routes.close(route_id)


@router.post("/{route_id}/cleanup")
def cleanup(route_id: str):
    return serving_routes.cleanup(route_id)


@router.get("/{route_id}/events")
def events(route_id: str, limit: int = Query(default=50, ge=1, le=500)):
    serving_routes.get_route(route_id)
    values = [value for value in serving_store.read()["requests"].values() if value["route_id"] == route_id]
    return sorted(values, key=lambda value: value["started_at"], reverse=True)[:limit]
