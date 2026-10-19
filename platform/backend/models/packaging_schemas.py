"""모델 패키징/배포 관련 Pydantic 스키마"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Framework = Literal["pytorch", "onnx", "tensorflow", "ridge"]
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


class PackageRecord(BaseModel):
    model_name: str
    version: str
    status: Literal["unbuilt", "building", "built", "failed", "unknown"] = "unbuilt"
    package_id: str | None = None
    image_tag: str | None = None
    base_image: str | None = None
    image_digest: str | None = None
    image_size_bytes: int | None = None
    artifact_id: str | None = None
    weights_checksum: str | None = None
    manifest_checksum: str | None = None
    requested_at: str | None = None
    built_at: str | None = None
    error: str | None = None
    builder_instance: str | None = None


class TrainingModelRegisterRequest(BaseModel):
    round_id: str = Field(..., min_length=1)
    version: str | None = None

    @field_validator("version")
    @classmethod
    def _check_version(cls, value):
        return ModelRegisterRequest._check_semver(value) if value is not None else None


class RidgePredictRequest(BaseModel):
    inputs: list[Any] = Field(..., min_length=1)


class ModelIdentityRequest(BaseModel):
    name: str = Field(..., min_length=1)
    version: str


class RidgeIdentityPredictRequest(ModelIdentityRequest, RidgePredictRequest):
    """slash를 포함한 실제 모델명을 JSON 정체성으로 전달한다."""


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
    status: Literal["active", "archived"] = "active"
    package: PackageRecord | None = None


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
    status: Literal["built"] = "built"
    package_id: str | None = None
    image_digest: str | None = None
    artifact_id: str | None = None
    weights_checksum: str | None = None
    manifest_checksum: str | None = None
    base_image: str | None = None


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
    interval_seconds: int | None = Field(default=None, ge=1, strict=True)
    probe_inputs: list[Any] | None = Field(default=None, min_length=1)
    request_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def execution_contract(self):
        import re
        if len(set(self.target_node_ids)) != len(self.target_node_ids):
            raise ValueError("배포 대상이 중복되었습니다")
        reserved = {"MODEL_NAME", "MODEL_VERSION", "MODEL_FRAMEWORK", "MODEL_PATH", "ARTIFACT_ROOT", "MODEL_META_PATH"}
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in reserved for key in self.env):
            raise ValueError("환경변수 이름 또는 모델 정체성 예약 변수를 확인하세요")
        if any("\x00" in value for value in self.env.values()):
            raise ValueError("환경변수에는 NUL을 사용할 수 없습니다")
        if self.strategy == "batch":
            self.interval_seconds = self.interval_seconds or 60
        elif self.interval_seconds is not None:
            raise ValueError("반복 주기는 일괄 배포에서만 설정합니다")
        return self


class DeploymentTargetResult(BaseModel):
    status: Literal["pending", "launching", "running", "failed"] = "pending"
    container_id: str | None = None
    image_id: str | None = None
    endpoint: str | None = None
    weights_checksum: str | None = None
    prediction_checksum: str | None = None
    verified_at: str | None = None
    error_code: str | None = None


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
    launch_pending: bool = False
    cleanup_pending: bool = False
    cleanup_results: dict[str, str] = Field(default_factory=dict)
    configuration: DeploymentRequest | None = None
    expected_image_id: str | None = None
    expected_identity: dict[str, str] = Field(default_factory=dict)
    target_results: dict[str, DeploymentTargetResult] = Field(default_factory=dict)
    verified_at: str | None = None
    is_schedule: bool = False
    schedule_active: bool = False
    interval_seconds: int | None = None
    next_due_at: str | None = None
    occurrence: int = 0
    opening_run_id: str | None = None
    current_run_id: str | None = None
    schedule_parent_id: str | None = None
    scheduled_at: str | None = None
    rollback_run_id: str | None = None
