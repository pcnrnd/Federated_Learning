"""Requests for operator-staged external result bundles."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.packaging_schemas import ModelRegisterRequest


class ExternalResultInspect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bundle_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class ExternalResultImport(ExternalResultInspect):
    name: str = Field(min_length=1, max_length=64)
    version: str

    @field_validator("version")
    @classmethod
    def check_version(cls, value: str) -> str:
        return ModelRegisterRequest._check_semver(value)
