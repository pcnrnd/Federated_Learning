"""A·B 테스트 API"""
from __future__ import annotations

from fastapi import APIRouter, Query

from models.maintenance_schemas import (
    ABTest,
    ABTestEvaluation,
    ABTestRequest,
)
from services import ab_test_service

router = APIRouter(prefix="/api/ab-tests", tags=["ab-tests"])


@router.get("", response_model=list[ABTest])
def list_tests_endpoint(status: str | None = Query(default=None)) -> list[ABTest]:
    return ab_test_service.list_tests(status=status)


@router.post("", response_model=ABTest, status_code=201)
def create_test_endpoint(request: ABTestRequest) -> ABTest:
    return ab_test_service.create_test(request)


@router.get("/{test_id}", response_model=ABTest)
def get_test_endpoint(test_id: str) -> ABTest:
    return ab_test_service.get_test(test_id)


@router.post("/{test_id}/evaluate", response_model=ABTestEvaluation)
def evaluate_endpoint(test_id: str) -> ABTestEvaluation:
    return ab_test_service.evaluate_test(test_id)


@router.post("/{test_id}/promote", response_model=ABTest)
def promote_endpoint(test_id: str) -> ABTest:
    return ab_test_service.promote_winner(test_id)


@router.post("/{test_id}/abort", response_model=ABTest)
def abort_endpoint(test_id: str) -> ABTest:
    return ab_test_service.abort_test(test_id)
