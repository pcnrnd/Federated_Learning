"""모델 lineage API"""
from __future__ import annotations

from fastapi import APIRouter

from models.maintenance_schemas import (
    LineageNode,
    ModelLineage,
    ModelLineageRequest,
)
from services import lineage_service

router = APIRouter(prefix="/api/lineage", tags=["lineage"])


@router.put("/{model_name}/{version}", response_model=ModelLineage)
def set_lineage_endpoint(
    model_name: str, version: str, request: ModelLineageRequest
) -> ModelLineage:
    return lineage_service.set_lineage(model_name, version, request)


@router.get("/{model_name}/{version}", response_model=ModelLineage)
def get_lineage_endpoint(model_name: str, version: str) -> ModelLineage:
    return lineage_service.get_lineage(model_name, version)


@router.get("/{model_name}/tree/", response_model=list[LineageNode])
def lineage_tree_endpoint(model_name: str) -> list[LineageNode]:
    return lineage_service.lineage_tree(model_name)


@router.get("/{model_name}/{version}/ancestors", response_model=list[ModelLineage])
def ancestors_endpoint(model_name: str, version: str) -> list[ModelLineage]:
    return lineage_service.ancestors(model_name, version)
