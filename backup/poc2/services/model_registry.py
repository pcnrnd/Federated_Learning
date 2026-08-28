"""모델 레지스트리 서비스 (SemVer 기반)"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from config.registry_manager import load_models, save_models
from models.packaging_schemas import ModelEntry, ModelRegisterRequest

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _semver_tuple(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split(".")
    return (int(major), int(minor), int(patch))


def list_models() -> list[ModelEntry]:
    """등록된 모든 모델/버전 평탄화 목록"""
    registry = load_models()
    entries: list[ModelEntry] = []
    for name, versions in registry.items():
        if not isinstance(versions, dict):
            continue
        for version, payload in versions.items():
            entries.append(ModelEntry(name=name, version=version, **payload))
    entries.sort(key=lambda e: (e.name, _semver_tuple(e.version)))
    return entries


def list_versions(name: str) -> list[ModelEntry]:
    """특정 모델명의 버전 목록 (SemVer 정렬, 최신 우선)"""
    registry = load_models()
    if name not in registry:
        raise HTTPException(status_code=404, detail=f"모델 '{name}'을 찾을 수 없습니다")
    versions = registry[name]
    entries = [
        ModelEntry(name=name, version=v, **payload)
        for v, payload in versions.items()
    ]
    entries.sort(key=lambda e: _semver_tuple(e.version), reverse=True)
    return entries


def get_model(name: str, version: str) -> ModelEntry:
    """모델 버전 단건 조회"""
    registry = load_models()
    if name not in registry or version not in registry[name]:
        raise HTTPException(
            status_code=404,
            detail=f"모델 '{name}@{version}'을 찾을 수 없습니다",
        )
    return ModelEntry(name=name, version=version, **registry[name][version])


def register_model(request: ModelRegisterRequest) -> ModelEntry:
    """신규 모델 버전 등록"""
    registry = load_models()
    versions = registry.setdefault(request.name, {})
    if request.version in versions:
        raise HTTPException(
            status_code=409,
            detail=f"'{request.name}@{request.version}'은 이미 등록되어 있습니다",
        )

    entry = ModelEntry(
        name=request.name,
        version=request.version,
        framework=request.framework,
        weights_path=request.weights_path,
        input_schema=request.input_schema,
        output_schema=request.output_schema,
        metadata=request.metadata,
        created_at=_now_iso(),
    )
    payload = entry.model_dump()
    payload.pop("name")
    payload.pop("version")
    versions[request.version] = payload
    save_models(registry)
    logger.info("모델 등록: %s@%s", request.name, request.version)
    return entry


def delete_model(name: str, version: str) -> None:
    """모델 버전 제거 (배포 중인 버전은 사전 점검 필요 — 호출 측 책임)"""
    registry = load_models()
    if name not in registry or version not in registry[name]:
        raise HTTPException(
            status_code=404,
            detail=f"모델 '{name}@{version}'을 찾을 수 없습니다",
        )
    del registry[name][version]
    if not registry[name]:
        del registry[name]
    save_models(registry)
    logger.info("모델 삭제: %s@%s", name, version)


def latest_version(name: str) -> ModelEntry:
    """SemVer 최신 버전"""
    versions = list_versions(name)
    return versions[0]
