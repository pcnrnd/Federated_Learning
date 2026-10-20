"""G3 영속 완료 결과를 불변 ridge artifact와 한 모델 버전으로 복구 가능하게 연결한다."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import yaml
from fastapi import HTTPException

from config import settings
from config.yaml_store import save_yaml_atomic
from models.packaging_schemas import ModelRegisterRequest
from services import model_registry, ridge_artifacts, training_round_service

logger = logging.getLogger(__name__)


def artifact_root():
    return settings.CONFIG_DIR / "model-artifacts"


def _state_path():
    return settings.CONFIG_DIR / "training-model-results.yaml"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load():
    path = _state_path()
    if not path.exists():
        return {}
    try:
        value = yaml.safe_load(path.read_text("utf-8"))
        if not isinstance(value, dict) or any(not isinstance(v, dict) for v in value.values()):
            raise ValueError("결과 등록 원장 형식 불일치")
        for identity, entry in value.items():
            if (entry.get("result_id") != identity or not isinstance(identity, str) or len(identity) != 64
                    or any(c not in "0123456789abcdef" for c in identity)
                    or entry.get("status") not in ("reserved", "artifact_ready", "registered", "deleted")
                    or not isinstance(entry.get("model_name"), str) or not entry["model_name"]
                    or not isinstance(entry.get("round_id"), str) or not entry["round_id"]):
                raise ValueError("결과 등록 원장 정체성 불일치")
            ModelRegisterRequest._check_semver(entry["version"])
        return value
    except (OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError) as exc:
        # 손상/일시 I/O 오류를 빈 원장으로 대체하면 삭제 모델이나 같은 결과를 다시 생성한다.
        raise HTTPException(status_code=503, detail="학습 결과 등록 원장을 읽을 수 없습니다") from exc


def _save(states):
    try:
        save_yaml_atomic(_state_path(), states)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="학습 결과 등록 원장을 저장할 수 없습니다") from exc


def _store(states, identity, **update):
    entry = {**states.get(identity, {}), **update, "updated_at": _now()}
    next_states = {**states, identity: entry}
    _save(next_states)
    states[identity] = entry
    return entry


def _next_version(name, base, states):
    versions = [model_registry._semver_tuple(base)]
    versions.extend(model_registry._semver_tuple(entry.version) for entry in model_registry.list_models()
                    if entry.name == name)
    versions.extend(model_registry._semver_tuple(entry["version"]) for entry in states.values()
                    if entry.get("model_name") == name and entry.get("version"))
    major, minor, patch = max(versions)
    return f"{major}.{minor}.{patch + 1}"


def assert_version_binding(name, version, result_id):
    """ridge 버전은 삭제/실패 이력이 있더라도 다른 완료 결과로 재사용하지 않는다."""
    with model_registry.REGISTRY_LOCK:
        for entry in _load().values():
            if entry.get("model_name") == name and entry.get("version") == version:
                if entry.get("result_id") != result_id or entry.get("status") == "deleted":
                    raise HTTPException(status_code=409, detail="다른 결과 또는 삭제 이력에 예약된 모델 버전입니다")


def _find_registered(result_id):
    matches = [entry for entry in model_registry.list_models()
               if entry.framework == "ridge" and entry.metadata.get("result_id") == result_id]
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="같은 학습 결과가 여러 모델 버전에 연결되어 있습니다")
    return matches[0] if matches else None


def _record_existing(states, result, existing):
    artifact = model_registry.get_ridge_artifact(existing)
    source = artifact.manifest["source_result"]
    if source["result_id"] != result["result_id"] or source["checksum"] != result["checksum"]:
        raise HTTPException(status_code=409, detail="등록 모델과 완료 학습 결과의 정체성 불일치")
    _store(states, result["result_id"], result_id=result["result_id"], round_id=result["round_id"],
           model_name=existing.name, version=existing.version, artifact_id=artifact.artifact_id,
           manifest_sha256=artifact.manifest_sha256, status="registered", error_code=None)
    return existing


def register_completed_result(round_id, *, version=None):
    """원장 예약→artifact 게시→레지스트리 등록→완료. 중간 오류는 같은 예약으로 재시도한다."""
    result = training_round_service.get_result(round_id).model_dump()
    if result["format"] != "ridge-v1":
        raise HTTPException(status_code=422, detail="실제 ridge 학습 완료 결과를 선택해야 합니다")
    job_id = training_round_service.get_round(round_id).job_id
    with model_registry.REGISTRY_LOCK:
        from services.retraining_service import reserve_registration
        reserve_registration(job_id, result["result_id"])
        states = _load()
        identity = result["result_id"]
        binding = states.get(identity)
        if binding and binding.get("status") == "deleted":
            raise HTTPException(status_code=409, detail="명시적으로 삭제된 학습 결과의 모델입니다")
        existing = _find_registered(identity)
        selected = binding.get("version") if binding else (existing.version if existing else None)
        if version is not None and selected is not None and version != selected:
            raise HTTPException(status_code=409, detail="이미 예약/등록된 결과의 버전을 바꿀 수 없습니다")
        if existing:
            return _record_existing(states, result, existing)
        if binding is None:
            chosen = version or _next_version(result["model_name"], result["version"], states)
            ModelRegisterRequest._check_semver(chosen)
            assert_version_binding(result["model_name"], chosen, identity)
            if any(entry.name == result["model_name"] and entry.version == chosen
                   for entry in model_registry.list_models()):
                raise HTTPException(status_code=409, detail="선택한 모델 버전이 이미 존재합니다")
            binding = _store(states, identity, result_id=identity, round_id=round_id,
                model_name=result["model_name"], version=chosen, status="reserved", error_code=None)
        try:
            return _publish_registration(states, result, binding)
        except (OSError, ValueError) as exc:
            _store(states, identity, error_code=type(exc).__name__)
            raise HTTPException(status_code=409, detail="학습 가중치 저장/무결성 검사가 실패했습니다") from exc


def _publish_registration(states, result, binding):
    if binding.get("artifact_id"):
        artifact = ridge_artifacts.load_artifact(artifact_root(), binding["artifact_id"],
                                                 expected_manifest_sha256=binding.get("manifest_sha256"))
    else:
        artifact = ridge_artifacts.save_artifact(artifact_root(), result, version=binding["version"])
    manifest = artifact.manifest
    if (manifest["source_result"]["result_id"] != result["result_id"]
            or manifest["model_name"] != binding["model_name"] or manifest["version"] != binding["version"]):
        raise ValueError("예약 모델과 불변 artifact의 정체성 불일치")
    _store(states, result["result_id"], artifact_id=artifact.artifact_id,
           manifest_sha256=artifact.manifest_sha256, status="artifact_ready", error_code=None)
    entry = model_registry.register_model(ModelRegisterRequest(name=binding["model_name"],
        version=binding["version"], framework="ridge", weights_path=str(artifact.weights_path),
        input_schema={"features": list(artifact.features), "dimension": len(artifact.features)},
        output_schema={"target": artifact.target},
        metadata={"artifact_id": artifact.artifact_id, "manifest_sha256": artifact.manifest_sha256,
                  "weights_sha256": artifact.weights_sha256, "result_id": result["result_id"],
                  "derived_from_round_id": result["round_id"], "algorithm": "fedavg", "rounds": 1}))
    _store(states, result["result_id"], status="registered", error_code=None)
    return entry


def suppress_result(entry):
    """레지스트리 삭제보다 먼저 tombstone을 써서 scheduler가 삭제 모델을 재생성하지 않게 한다."""
    with model_registry.REGISTRY_LOCK:
        states = _load()
        identity = entry.metadata["result_id"]
        _store(states, identity, result_id=identity, round_id=entry.metadata.get("derived_from_round_id"),
               model_name=entry.name, version=entry.version, status="deleted", error_code=None)


def list_registrations():
    with model_registry.REGISTRY_LOCK:
        return list(_load().values())


def reconcile_completed_results():
    """완료 결과를 매 tick 재발견한다. 레지스트리/원장 쓰기 실패 뒤 재시작도 동일 경로다."""
    registered = []
    for entry in training_round_service.list_rounds(status="completed"):
        if entry.learning is None or entry.result is None or entry.result.get("format") != "ridge-v1":
            continue
        try:
            with model_registry.REGISTRY_LOCK:
                state = _load().get(entry.result.get("result_id"), {})
                if state.get("status") == "deleted":
                    continue
            register_completed_result(entry.round_id)
            registered.append(entry.round_id)
        except (HTTPException, OSError, ValueError) as exc:
            logger.warning("완료 학습 모델 등록 재시도 대기: round=%s type=%s", entry.round_id, type(exc).__name__)
    return registered
