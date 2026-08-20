"""모델 패키징/배포 관련 Pydantic 스키마"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Framework = Literal["pytorch", "onnx", "tensorflow"]
DeploymentStrategyName = Literal["realtime", "batch", "edge"]
DeploymentStatus = Literal["pending", "running", "failed", "rolled_back", "stopped"]


class ModelRegisterRequest(BaseModel):
    """모델 등록 요청 (가중치 파일은 사전 업로드되어 있다고 가정)"""

    name: str = Field(..., min_length=1, max_length=64)
    version: str = Field(..., description="SemVer 형식 (예: 1.2.3)")
    framework: Framework
    weights_path: str = Field(..., description="가중치 파일 경로 (.pt/.pth/.onnx)")
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def _check_semver(cls, value: str) -> str:
        parts = value.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError("version은 SemVer 형식이어야 합니다 (예: 1.2.3)")
        return value


class ModelEntry(BaseModel):
    """모델 레지스트리 엔트리"""

    name: str
    version: str
    framework: Framework
    weights_path: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class PackagingRequest(BaseModel):
    """패키징(Docker 이미지 빌드) 요청"""

    model_name: str
    version: str
    base_image: str = Field(default="python:3.11-slim")
    extra_requirements: list[str] = Field(default_factory=list)
    image_tag: str | None = Field(
        default=None,
        description="미지정 시 fed-model-{name}:{version}",
    )


class PackagingResult(BaseModel):
    """패키징 결과"""

    model_name: str
    version: str
    image_tag: str
    image_size_bytes: int
    built_at: str


class DeploymentRequest(BaseModel):
    """배포 요청"""

    model_name: str
    version: str
    strategy: DeploymentStrategyName
    target_node_ids: list[str] = Field(..., min_length=1)
    image_tag: str | None = Field(default=None, description="미지정 시 패키징 결과 자동 사용")
    container_name_prefix: str = Field(default="fed-model")
    inference_port: int = Field(default=8501, ge=1, le=65535)
    env: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)


class DeploymentEntry(BaseModel):
    """배포 기록"""

    deployment_id: str
    model_name: str
    version: str
    image_tag: str
    strategy: DeploymentStrategyName
    target_node_ids: list[str]
    container_map: dict[str, str] = Field(
        default_factory=dict,
        description="node_id -> container_id",
    )
    status: DeploymentStatus
    created_at: str
    previous_deployment_id: str | None = None
    error: str | None = None
