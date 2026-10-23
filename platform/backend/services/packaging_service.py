"""모델 패키징 서비스: 모델 → Docker 이미지 빌드"""
from __future__ import annotations

import json
import hashlib
import logging
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import docker
from docker.errors import BuildError, DockerException
from fastapi import HTTPException
from jinja2 import Environment, FileSystemLoader, select_autoescape

from models.packaging_schemas import (
    ModelEntry,
    PackagingRequest,
    PackagingResult,
    PackageRecord,
)
from services import model_registry
from services.model_registry import get_model

logger = logging.getLogger(__name__)
_INSTANCE = uuid.uuid4().hex
_ACTIVE_BUILDS: set[str] = set()

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(default=False),
    keep_trailing_newline=True,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_image_tag(name: str, version: str) -> str:
    slug = re.sub(r"[^a-z0-9_.-]", "-", name.lower()).strip(".-")
    if not slug or slug != name:
        slug = (slug or "model") + "-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    return f"fed-model-{slug}:{version}"


def _docker_env(value):
    return value if re.fullmatch(r"[A-Za-z0-9_.-]+", value) else json.dumps(value, ensure_ascii=False)


def _render_dockerfile(entry: ModelEntry, request: PackagingRequest, weights_checksum="") -> str:
    template = _env.get_template("Dockerfile.inference.j2")
    return template.render(
        base_image=request.base_image,
        model_name=entry.name,
        model_name_env=_docker_env(entry.name),
        version=entry.version,
        framework=entry.framework,
        weights_filename=Path(entry.weights_path).name,
        extra_requirements=request.extra_requirements,
        artifact_id=entry.metadata.get("artifact_id", ""),
        manifest_checksum=entry.metadata.get("manifest_sha256", ""),
        weights_checksum=weights_checksum,
    )


def _render_inference_server(entry: ModelEntry, weights_checksum="") -> str:
    template = _env.get_template("inference_server.py.j2")
    return template.render(
        model_name=entry.name,
        version=entry.version,
        framework=entry.framework,
        weights_filename=Path(entry.weights_path).name,
        artifact_id=entry.metadata.get("artifact_id", ""),
        manifest_checksum=entry.metadata.get("manifest_sha256", ""),
        weights_checksum=weights_checksum,
    )


def _prepare_build_context(entry: ModelEntry, request: PackagingRequest, ctx: Path) -> dict:
    """Docker 빌드 컨텍스트 디렉토리에 필요한 파일을 모음"""
    weights_src = Path(entry.weights_path)
    if not weights_src.is_file() or weights_src.stat().st_size == 0:
        raise HTTPException(status_code=409, detail="실제 가중치 파일이 없거나 비어 있습니다")
    if entry.framework == "ridge":
        artifact = model_registry.get_ridge_artifact(entry)
        weights_dir = ctx / "artifacts" / artifact.artifact_id
        weights_dir.mkdir(parents=True)
        for name in ("weights.json", "manifest.json"):
            shutil.copy2(artifact.directory / name, weights_dir / name)
        shutil.copy2(Path(__file__).with_name("ridge_artifacts.py"), ctx / "ridge_artifacts.py")
        # 복사한 실제 bytes도 등록 checksum과 동일해야 한다.
        from services.ridge_artifacts import load_artifact
        load_artifact(ctx / "artifacts", artifact.artifact_id, expected_manifest_sha256=artifact.manifest_sha256)
    else:
        weights_dir = ctx / "weights"
        weights_dir.mkdir(parents=True)
        shutil.copy2(weights_src, weights_dir / weights_src.name)
    checksum = hashlib.sha256((weights_dir / weights_src.name).read_bytes()).hexdigest()

    (ctx / "Dockerfile").write_text(_render_dockerfile(entry, request, checksum), encoding="utf-8")
    (ctx / "inference_server.py").write_text(_render_inference_server(entry, checksum), encoding="utf-8")

    meta = {
        "name": entry.name,
        "version": entry.version,
        "framework": entry.framework,
        "input_schema": entry.input_schema,
        "output_schema": entry.output_schema,
        "metadata": entry.metadata,
        "weights_checksum": checksum,
    }
    (ctx / "model_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    return meta


def build_package(request: PackagingRequest) -> PackagingResult:
    """모델 레지스트리 엔트리를 기반으로 Docker 이미지를 빌드한다.

    빌드는 대시보드 컨테이너에 마운트된 호스트 Docker 소켓을 통해 수행된다
    (compose.dashboard.yaml에서 docker.sock 바인드마운트 사용).
    """
    entry, record = _reserve(request)
    return _execute_build(entry, request, record)


def get_package(name, version):
    with model_registry.REGISTRY_LOCK:
        entry = get_model(name, version)
        record = entry.package or PackageRecord(model_name=name, version=version)
        if record.status == "building" and (record.builder_instance != _INSTANCE or record.package_id not in _ACTIVE_BUILDS):
            record = record.model_copy(update={"status": "unknown", "error": "서버 재시작 후 빌드 결과 확인이 필요합니다"})
            model_registry.update_package(name, version, record)
        return record


def list_packages():
    return [get_package(entry.name, entry.version) for entry in model_registry.list_models()]


def _reserve(request):
    with model_registry.REGISTRY_LOCK:
        entry = get_model(request.model_name, request.version)
        if entry.status != "active":
            raise HTTPException(status_code=409, detail="보관한 모델은 패키징할 수 없습니다")
        if get_package(entry.name, entry.version).status == "building":
            raise HTTPException(status_code=409, detail="이 모델 버전의 빌드가 이미 진행 중입니다")
        path = Path(entry.weights_path)
        if not path.is_file() or path.stat().st_size == 0:
            raise HTTPException(status_code=409, detail="실제 가중치 파일이 없거나 비어 있습니다")
        if entry.framework == "ridge":
            model_registry.get_ridge_artifact(entry)
        record = PackageRecord(model_name=entry.name, version=entry.version, status="building",
            package_id=uuid.uuid4().hex, image_tag=request.image_tag or _default_image_tag(entry.name, entry.version),
            base_image=request.base_image,
            requested_at=_now_iso(), builder_instance=_INSTANCE, artifact_id=entry.metadata.get("artifact_id"),
            weights_checksum=entry.metadata.get("weights_sha256"), manifest_checksum=entry.metadata.get("manifest_sha256"))
        model_registry.update_package(entry.name, entry.version, record)
        _ACTIVE_BUILDS.add(record.package_id)
        return entry, record


def request_build(request, background_tasks):
    entry, record = _reserve(request)
    background_tasks.add_task(_background_build, entry, request, record)
    return record


def _background_build(entry, request, record):
    try:
        _execute_build(entry, request, record)
    except (HTTPException, OSError, ValueError):
        logger.warning("비동기 이미지 빌드 실패: %s@%s", entry.name, entry.version)


def _image_digest(image):
    value = getattr(image, "id", None)
    return value if isinstance(value, str) else image.attrs.get("Id")


def _verify_ridge_image(entry, image, checksum):
    image_id = _image_digest(image)
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise ValueError("빌드된 ridge 이미지 digest가 없습니다")
    labels = image.attrs.get("Config", {}).get("Labels", {}) or {}
    for key, expected in (("fed.artifact_id", entry.metadata["artifact_id"]),
                          ("fed.manifest_checksum", entry.metadata["manifest_sha256"]),
                          ("fed.weights_checksum", checksum)):
        if labels.get(key) != expected:
            raise ValueError("빌드된 이미지와 가중치 정체성 불일치")


def _execute_build(entry, request, record):
    client = None
    try:
        with tempfile.TemporaryDirectory(prefix="fed-pkg-") as tmp:
            context = Path(tmp)
            descriptor = _prepare_build_context(entry, request, context)
            client = docker.from_env()
            image, _logs = client.images.build(path=str(context), tag=record.image_tag,
                                               rm=True, pull=False, forcerm=True)
            checksum = descriptor["weights_checksum"]
            if entry.framework == "ridge":
                _verify_ridge_image(entry, image, checksum)
            result = PackagingResult(model_name=entry.name, version=entry.version, image_tag=record.image_tag,
                image_size_bytes=int(image.attrs.get("Size", 0)), built_at=_now_iso(), image_digest=_image_digest(image),
                package_id=record.package_id, artifact_id=record.artifact_id,
                weights_checksum=checksum, manifest_checksum=record.manifest_checksum, base_image=request.base_image)
        model_registry.update_package(entry.name, entry.version, PackageRecord(**result.model_dump(),
            requested_at=record.requested_at, builder_instance=_INSTANCE))
        return result
    except (OSError, ValueError, DockerException, HTTPException) as exc:
        failed = record.model_copy(update={"status": "failed", "error": f"이미지 빌드 실패 ({type(exc).__name__})"})
        model_registry.update_package(entry.name, entry.version, failed)
        if isinstance(exc, HTTPException):
            raise
        code = 400 if isinstance(exc, BuildError) else 500
        raise HTTPException(status_code=code, detail=failed.error) from exc
    finally:
        with model_registry.REGISTRY_LOCK:
            _ACTIVE_BUILDS.discard(record.package_id)
        if client is not None:
            client.close()


def render_dockerfile_only(request: PackagingRequest) -> str:
    """이미지 빌드 없이 Dockerfile 텍스트만 렌더링 (드라이런/디버깅용)"""
    entry = get_model(request.model_name, request.version)
    return _render_dockerfile(entry, request)
