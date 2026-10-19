"""배포 전략 — Strategy 패턴 (realtime / batch / edge)

배포 추상화:
  * realtime — 즉시 컨테이너 기동, restart=always
  * batch    — 영속 일정 서비스가 도래한 회차만 기동
  * edge     — role=client 노드 대상 + edge 라벨 부여
각 전략은 동일한 인터페이스를 가지며, 노드별로 컨테이너를 생성한다.
"""
from __future__ import annotations

import logging
import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

import docker
from docker.errors import APIError, DockerException, ImageNotFound, NotFound
from fastapi import HTTPException

from models.packaging_schemas import DeploymentRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NodeDeployContext:
    """전략에 전달되는 노드별 컨텍스트"""

    node_id: str
    docker_client: docker.DockerClient
    node_info: dict[str, str]  # servers.yaml의 노드 정보


@dataclass(frozen=True)
class StrategyResult:
    """단일 노드 배포 결과"""

    node_id: str
    container_id: str


class DeploymentStrategy(Protocol):
    """배포 전략 Protocol"""

    name: str

    def deploy_to_node(
        self,
        ctx: NodeDeployContext,
        request: DeploymentRequest,
        deployment_id: str,
    ) -> StrategyResult: ...


def _container_name(prefix: str, model: str, version: str, deployment_id: str) -> str:
    safe_prefix = re.sub(r"[^a-zA-Z0-9_.-]", "-", prefix)[:40].strip(".-") or "fed-model"
    identity = hashlib.sha256(f"{model}\0{version}".encode()).hexdigest()[:16]
    return f"{safe_prefix}-{identity}-{deployment_id}"


def _common_labels(
    request: DeploymentRequest,
    deployment_id: str,
    strategy: str,
) -> dict[str, str]:
    labels = {
        **request.labels,
        "fed.deployment_id": deployment_id,
        "fed.model": request.model_name,
        "fed.version": request.version,
        "fed.strategy": strategy,
    }
    return labels


def _ensure_image(client: docker.DockerClient, image_tag: str) -> None:
    """이미지 존재 확인 — 없으면 pull 시도"""
    try:
        client.images.get(image_tag)
        return
    except ImageNotFound:
        pass
    try:
        logger.info("이미지 pull 시도: %s", image_tag)
        client.images.pull(image_tag)
    except DockerException as exc:
        raise HTTPException(
            status_code=400,
            detail=f"이미지 '{image_tag}' 사용 불가: {exc}",
        ) from exc


def _run_container(
    ctx: NodeDeployContext,
    request: DeploymentRequest,
    deployment_id: str,
    strategy: str,
    *,
    autostart: bool,
    restart_policy: dict[str, str | int] | None,
) -> StrategyResult:
    image_tag = request.image_tag
    if not image_tag:
        raise HTTPException(status_code=400, detail="image_tag가 필요합니다")

    _ensure_image(ctx.docker_client, image_tag)

    name = _container_name(
        request.container_name_prefix,
        request.model_name,
        request.version,
        deployment_id,
    )
    labels = _common_labels(request, deployment_id, strategy)
    custom_port = {} if request.inference_port == 8501 else {
        "command": ["uvicorn", "inference_server:app", "--host", "0.0.0.0", "--port", str(request.inference_port)],
        "healthcheck": {"test": ["CMD", "python", "-c",
            f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{request.inference_port}/health')"]},
    }
    try:
        try:
            container = ctx.docker_client.containers.get(name)
        except NotFound:
            container = ctx.docker_client.containers.create(
                image=image_tag,
                name=name,
                environment=request.env,
                labels=labels,
                ports={f"{request.inference_port}/tcp": None},
                restart_policy=restart_policy,
                detach=True,
                **custom_port,
            )
        else:
            actual_labels = container.labels or {}
            if (container.image.id != image_tag or any(actual_labels.get(key) != labels[key]
                    for key in ("fed.deployment_id", "fed.model", "fed.version", "fed.strategy"))):
                raise HTTPException(status_code=409, detail="같은 실행 이름의 컨테이너 정체성이 다릅니다")
        container.reload()
        if autostart and container.status != "running":
            container.start()
    except APIError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"노드 '{ctx.node_id}' 컨테이너 생성 실패: {exc}",
        ) from exc

    logger.info(
        "배포(%s): node=%s container=%s image=%s autostart=%s",
        strategy,
        ctx.node_id,
        container.short_id,
        image_tag,
        autostart,
    )
    return StrategyResult(node_id=ctx.node_id, container_id=container.id)


class RealtimeStrategy:
    name = "realtime"

    def deploy_to_node(
        self,
        ctx: NodeDeployContext,
        request: DeploymentRequest,
        deployment_id: str,
    ) -> StrategyResult:
        return _run_container(
            ctx,
            request,
            deployment_id,
            self.name,
            autostart=True,
            restart_policy={"Name": "always"},
        )


class BatchStrategy:
    """일정 서비스가 due 회차에서 호출한다. 실제 실행·검증 전에는 running이 아니다."""

    name = "batch"

    def deploy_to_node(
        self,
        ctx: NodeDeployContext,
        request: DeploymentRequest,
        deployment_id: str,
    ) -> StrategyResult:
        request_with_label = request.model_copy(
            update={"labels": {**request.labels, "fed.batch": "scheduled-occurrence"}},
        )
        return _run_container(
            ctx,
            request_with_label,
            deployment_id,
            self.name,
            autostart=True,
            restart_policy={"Name": "unless-stopped"},
        )


class EdgeStrategy:
    """엣지 배포: role=client 노드에만 허용."""

    name = "edge"

    def deploy_to_node(
        self,
        ctx: NodeDeployContext,
        request: DeploymentRequest,
        deployment_id: str,
    ) -> StrategyResult:
        if ctx.node_info.get("role") != "client":
            raise HTTPException(
                status_code=400,
                detail=f"노드 '{ctx.node_id}'는 엣지 배포 대상이 아닙니다 (role!=client)",
            )
        request_with_label = request.model_copy(
            update={"labels": {**request.labels, "fed.edge": "1"}},
        )
        return _run_container(
            ctx,
            request_with_label,
            deployment_id,
            self.name,
            autostart=True,
            restart_policy={"Name": "unless-stopped"},
        )


_STRATEGIES: dict[str, DeploymentStrategy] = {
    RealtimeStrategy.name: RealtimeStrategy(),
    BatchStrategy.name: BatchStrategy(),
    EdgeStrategy.name: EdgeStrategy(),
}


def get_strategy(name: str) -> DeploymentStrategy:
    if name not in _STRATEGIES:
        raise HTTPException(status_code=400, detail=f"알 수 없는 배포 전략: {name}")
    return _STRATEGIES[name]
