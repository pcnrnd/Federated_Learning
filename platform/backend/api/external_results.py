"""Completed-result interchange, independent from native/Flower training jobs."""

from fastapi import APIRouter, Query, Response

from models.external_result_schemas import ExternalResultImport, ExternalResultInspect
from models.packaging_schemas import ModelEntry
from services import external_results

router = APIRouter(prefix="/api/external-results", tags=["external-results"])


@router.post("/inspect")
def inspect_result(payload: ExternalResultInspect) -> dict:
    return external_results.inspect_result(payload.bundle_id)


@router.post("/import", response_model=ModelEntry, status_code=201)
def import_result(payload: ExternalResultImport, response: Response) -> ModelEntry:
    entry, created = external_results.import_result(payload)
    if not created:
        response.status_code = 200
    return entry


@router.get("")
def get_result(name: str = Query(...), version: str = Query(...)) -> dict:
    return external_results.get_result(name, version)
