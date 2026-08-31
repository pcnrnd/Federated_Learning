"""모델 패키징 서비스: 모델 → Docker 이미지 빌드"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
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
)
from services.model_registry import get_model

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(default=False),
    keep_trailing_newline=True,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_image_tag(name: str, version: str) -> str:
    return f"fed-model-{name}:{version}"


def _render_dockerfile(entry: ModelEntry, request: PackagingRequest) -> str:
    template = _env.get_template("Dockerfile.inference.j2")
    return template.render(
        base_image=request.base_image,
        model_name=entry.name,
        version=entry.version,
        framework=entry.framework,
        weights_filename=Path(entry.weights_path).name,
        extra_requirements=request.extra_requirements,
    )


def _render_inference_server(entry: ModelEntry) -> str:
    template = _env.get_template("inference_server.py.j2")
    return template.render(
        model_name=entry.name,
        version=entry.version,
        framework=entry.framework,
        weights_filename=Path(entry.weights_path).name,
    )


def _prepare_build_context(entry: ModelEntry, request: PackagingRequest, ctx: Path) -> None:
    """Docker 빌드 컨텍스트 디렉토리에 필요한 파일을 모음"""
    weights_src = Path(entry.weights_path)
    weights_dir = ctx / "weights"
    weights_dir.mkdir(parents=True, exist_ok=True)
    if weights_src.exists():
        shutil.copy2(weights_src, weights_dir / weights_src.name)
    else:
        # 실제 가중치가 없는 환경에서도 빌드 자체는 진행 가능하도록 placeholder
        (weights_dir / weights_src.name).write_bytes(b"")
        logger.warning("가중치 파일 없음 — 빈 파일로 컨텍스트 생성: %s", weights_src)

    (ctx / "Dockerfile").write_text(_render_dockerfile(entry, request), encoding="utf-8")
    (ctx / "inference_server.py").write_text(_render_inference_server(entry), encoding="utf-8")

    meta = {
        "name": entry.name,
        "version": entry.version,
        "framework": entry.framework,
        "input_schema": entry.input_schema,
        "output_schema": entry.output_schema,
        "metadata": entry.metadata,
    }
    (ctx / "model_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")


def build_package(request: PackagingRequest) -> PackagingResult:
    """모델 레지스트리 엔트리를 기반으로 Docker 이미지를 빌드한다.

    빌드는 대시보드 컨테이너에 마운트된 호스트 Docker 소켓을 통해 수행된다
    (compose.dashboard.yaml에서 docker.sock 바인드마운트 사용).
    """
    entry = get_model(request.model_name, request.version)
    image_tag = request.image_tag or _default_image_tag(entry.name, entry.version)

    try:
        client = docker.from_env()
    except DockerException as exc:
        raise HTTPException(status_code=500, detail=f"Docker 데몬 연결 실패: {exc}") from exc

    with tempfile.TemporaryDirectory(prefix="fed-pkg-") as tmp:
        ctx_dir = Path(tmp)
        _prepare_build_context(entry, request, ctx_dir)

        logger.info("이미지 빌드 시작: %s (context=%s)", image_tag, ctx_dir)
        try:
            image, _logs = client.images.build(
                path=str(ctx_dir),
                tag=image_tag,
                rm=True,
                pull=False,
                forcerm=True,
            )
        except BuildError as exc:
            raise HTTPException(status_code=400, detail=f"이미지 빌드 실패: {exc}") from exc
        except DockerException as exc:
            raise HTTPException(status_code=500, detail=f"Docker 오류: {exc}") from exc

    size_bytes = int(image.attrs.get("Size", 0))
    logger.info("이미지 빌드 완료: %s (%s bytes)", image_tag, size_bytes)
    return PackagingResult(
        model_name=entry.name,
        version=entry.version,
        image_tag=image_tag,
        image_size_bytes=size_bytes,
        built_at=_now_iso(),
    )


def render_dockerfile_only(request: PackagingRequest) -> str:
    """이미지 빌드 없이 Dockerfile 텍스트만 렌더링 (드라이런/디버깅용)"""
    entry = get_model(request.model_name, request.version)
    return _render_dockerfile(entry, request)
