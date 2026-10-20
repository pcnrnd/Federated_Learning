"""원시 값 없이 저장하는 공통 분포 설정과 명시적 기준 선택."""
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

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
