"""모델 레지스트리 서비스 (SemVer 기반)"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from threading import RLock

from fastapi import HTTPException

from config.registry_manager import load_deployments, load_models, save_models
from models.packaging_schemas import ModelEntry, ModelRegisterRequest, PackageRecord
from services import ridge_artifacts

logger = logging.getLogger(__name__)
REGISTRY_LOCK = RLock()


def _locked(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with REGISTRY_LOCK:
            return function(*args, **kwargs)
    return wrapped


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _semver_tuple(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split(".")
    return (int(major), int(minor), int(patch))


@_locked
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


@_locked
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


@_locked
def get_model(name: str, version: str) -> ModelEntry:
    """모델 버전 단건 조회"""
    registry = load_models()
    if name not in registry or version not in registry[name]:
        raise HTTPException(
            status_code=404,
            detail=f"모델 '{name}@{version}'을 찾을 수 없습니다",
        )
    return ModelEntry(name=name, version=version, **registry[name][version])


@_locked
def register_model(request: ModelRegisterRequest) -> ModelEntry:
    """신규 모델 버전 등록"""
    registry = load_models()
    versions = registry.setdefault(request.name, {})
    if request.version in versions:
        raise HTTPException(
            status_code=409,
            detail=f"'{request.name}@{request.version}'은 이미 등록되어 있습니다",
        )

    metadata = dict(request.metadata)
    if request.framework == "ridge":
        metadata.update(_ridge_metadata(request))
        from services.training_model_service import assert_version_binding
        assert_version_binding(request.name, request.version, metadata["result_id"])
        if any(entry.metadata.get("result_id") == metadata["result_id"] for entry in list_models()):
            raise HTTPException(status_code=409, detail="이 확정 학습 결과는 이미 등록되어 있습니다")
    entry = ModelEntry(
        name=request.name,
        version=request.version,
        framework=request.framework,
        weights_path=request.weights_path,
        input_schema=request.input_schema,
        output_schema=request.output_schema,
        metadata=metadata,
        created_at=_now_iso(),
    )
    payload = entry.model_dump()
    payload.pop("name")
    payload.pop("version")
    versions[request.version] = payload
    save_models(registry)
    logger.info("모델 등록: %s@%s", request.name, request.version)
    return entry


@_locked
def delete_model(name: str, version: str) -> None:
    """사용 중/복구 참조를 검사하고 삭제 의도를 먼저 영속한다. 불변 파일은 보존한다."""
    entry = get_model(name, version)
    _check_references(name, version)
    if entry.framework == "ridge" and entry.metadata.get("result_id"):
        from services.training_model_service import suppress_result
        suppress_result(entry)
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


def get_ridge_artifact(entry):
    if entry.framework != "ridge":
        raise HTTPException(status_code=422, detail="ridge 모델이 아닙니다")
    path = Path(entry.weights_path)
    try:
        if path.name != "weights.json":
            raise ValueError("ridge weights 경로 계약 불일치")
        artifact = ridge_artifacts.load_artifact(path.parent.parent, path.parent.name,
            expected_manifest_sha256=entry.metadata.get("manifest_sha256"))
        manifest = artifact.manifest
        if manifest["model_name"] != entry.name or manifest["version"] != entry.version:
            raise ValueError("모델/버전과 artifact 정체성 불일치")
        for key, actual in (("artifact_id", artifact.artifact_id), ("weights_sha256", artifact.weights_sha256),
                            ("result_id", manifest["source_result"]["result_id"])):
            if entry.metadata.get(key) not in (None, actual):
                raise ValueError("등록 정체성과 실제 artifact 불일치")
        return artifact
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="ridge 가중치/manifest가 없거나 무결성이 일치하지 않습니다") from exc


def _ridge_metadata(request):
    temporary = ModelEntry(**request.model_dump(), created_at=_now_iso())
    artifact = get_ridge_artifact(temporary)
    return dict(artifact_id=artifact.artifact_id, weights_sha256=artifact.weights_sha256,
                manifest_sha256=artifact.manifest_sha256,
                result_id=artifact.manifest["source_result"]["result_id"],
                derived_from_round_id=artifact.manifest["source_result"]["round_id"],
                features=list(artifact.features), target=artifact.target, format="ridge-v1")


def _check_references(name, version):
    deployments = load_deployments()
    from config.maintenance_manager import load_shadows
    from services import serving_store
    state = serving_store.read()
    for shadow in load_shadows().values():
        outcome = state["shadows"].get(shadow.get("shadow_id"), {})
        status = outcome.get("status", shadow.get("status"))
        if (shadow.get("model_name") == name and shadow.get("shadow_version") == version
                and status in ("initializing", "active", "failed")):
            raise HTTPException(status_code=409, detail="진행/미확인 shadow 의도에 참조된 모델 버전입니다")
    active = [value for value in deployments.values() if value.get("status") in ("running", "pending")
        or bool(value.get("container_map")) or value.get("launch_pending") or value.get("cleanup_pending")
        or (value.get("status") == "failed" and value.get("rollback_run_id"))]
    rollback_ids = {value.get("previous_deployment_id") for value in active}
    for identity, value in deployments.items():
        referenced = value.get("status") in ("running", "pending") or identity in rollback_ids
        # 실패 응답이어도 실제 컨테이너가 남은 배포는 삭제/보관으로 숨기지 않는다.
        referenced = referenced or bool(value.get("container_map")) or value.get("cleanup_pending") or value.get("launch_pending")
        referenced = referenced or serving_store.references(identity)
        if referenced and value.get("model_name") == name and value.get("version") == version:
            raise HTTPException(status_code=409, detail="실행/미확인 정리 또는 rollback에 참조된 모델 버전입니다")
    entry = get_model(name, version)
    from services.packaging_service import get_package
    if entry.package and get_package(name, version).status == "building":
        raise HTTPException(status_code=409, detail="이미지 빌드 중인 모델 버전입니다")


@_locked
def archive_model(name, version):
    _check_references(name, version)
    registry = load_models()
    registry[name][version]["status"] = "archived"
    save_models(registry)
    return get_model(name, version)


@_locked
def restore_archived_model(name, version):
    entry = get_model(name, version)
    if entry.framework == "ridge":
        get_ridge_artifact(entry)
    elif not Path(entry.weights_path).is_file() or Path(entry.weights_path).stat().st_size == 0:
        raise HTTPException(status_code=409, detail="복원할 실제 가중치 파일을 확인하세요")
    values = load_models()
    values[name][version]["status"] = "active"
    save_models(values)
    return get_model(name, version)


@_locked
def update_package(name, version, record: PackageRecord):
    get_model(name, version)
    if record.model_name != name or record.version != version:
        raise ValueError("패키지 모델/버전 계약 불일치")
    registry = load_models()
    registry[name][version]["package"] = record.model_dump()
    save_models(registry)
    return record


def predict_model(name, version, inputs):
    entry = get_model(name, version)
    if entry.status != "active":
        raise HTTPException(status_code=409, detail="보관한 모델은 추론할 수 없습니다")
    artifact = get_ridge_artifact(entry)
    try:
        outputs = ridge_artifacts.predict(artifact, inputs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return dict(model=name, version=version, artifact_id=artifact.artifact_id,
                weights_checksum=artifact.weights_sha256, result_id=artifact.manifest["source_result"]["result_id"],
                predictions=outputs)
