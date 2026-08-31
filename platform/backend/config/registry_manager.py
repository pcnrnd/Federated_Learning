"""모델 레지스트리/배포 기록 YAML 영속화"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from storage.factory import StorageDomain, get_repository

from .settings import CONFIG_DIR

logger = logging.getLogger(__name__)

MODELS_FILE: Path = CONFIG_DIR / "models.yaml"
DEPLOYMENTS_FILE: Path = CONFIG_DIR / "deployments.yaml"


def _save_with_http(repo_save, data: dict[str, Any]) -> None:
    """저장 실패 시 FastAPI 500으로 변환한다."""
    try:
        repo_save(data)
    except OSError as exc:
        logger.error("저장 실패: %s", exc)
        raise HTTPException(status_code=500, detail=f"파일 저장 실패: {exc}") from exc


def load_models() -> dict[str, Any]:
    """전체 모델 레지스트리 로드 ({name: {version: ModelEntry-dict}})"""
    return get_repository(StorageDomain.MODELS, MODELS_FILE).load()


def save_models(models: dict[str, Any]) -> None:
    _save_with_http(get_repository(StorageDomain.MODELS, MODELS_FILE).save, models)


def load_deployments() -> dict[str, Any]:
    """전체 배포 기록 로드 ({deployment_id: DeploymentEntry-dict})"""
    return get_repository(StorageDomain.DEPLOYMENTS, DEPLOYMENTS_FILE).load()


def save_deployments(deployments: dict[str, Any]) -> None:
    _save_with_http(
        get_repository(StorageDomain.DEPLOYMENTS, DEPLOYMENTS_FILE).save,
        deployments,
    )
