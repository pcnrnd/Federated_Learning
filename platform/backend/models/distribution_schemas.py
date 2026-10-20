"""원시 값 없이 저장하는 공통 분포 설정과 명시적 기준 선택."""
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from silo_sdk.distributions import edges


class DistributionConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_name: str
    version: str
    node_ids: list[str] = Field(min_length=1)
    feature: str
    feature_columns: list[str] = Field(min_length=1)
    bin_edges: list[float]
    schema_fingerprint: str
    recipe_name: str
    recipe_version: str
    recipe_hash: str
    target_column: str
    entity_id_columns: list[str] = Field(min_length=1)
    window_seconds: StrictInt = Field(ge=1, le=86400)

    @field_validator("bin_edges", mode="before")
    @classmethod
    def _finite_edges(cls, value):
        return edges(value)


class DistributionBaselineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str


class DistributionPolicyRequest(BaseModel):
    """PSI는 확률이 아니다. 유효 표본 수/신선도와 실제 적용 임계값을 명시한다."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    config_id: str
    warning_threshold: float = Field(ge=0)
    critical_threshold: float = Field(gt=0)
    min_valid_count: StrictInt = Field(ge=1)
    max_age_seconds: StrictInt = Field(ge=1)

    @field_validator("warning_threshold", "critical_threshold", mode="before")
    @classmethod
    def _number(cls, value):
        if type(value) not in (int, float):
            raise ValueError("PSI 임계값은 숫자여야 합니다")
        return value

    @model_validator(mode="after")
    def _ordered(self):
        if self.warning_threshold >= self.critical_threshold:
            raise ValueError("경고 PSI 임계값은 경보 임계값보다 작아야 합니다")
        return self
