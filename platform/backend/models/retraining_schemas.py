"""원시 입력 없이 실제 재교육 실행을 고정하는 설정/명령 계약."""
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


class RetrainCleaningOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_attempts: StrictInt = Field(default=3, ge=1, le=10)
    retry_backoff_seconds: StrictInt = Field(default=5, ge=0, le=3600)
    timeout_seconds: StrictInt = Field(default=300, ge=1, le=86400)
    partitions: StrictInt = Field(default=4, ge=1, le=32)
    parallelism: StrictInt = Field(default=2, ge=1, le=8)


class RetrainLearningOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    l2: float = Field(default=0.001, ge=0, strict=True)
    step_size: float = Field(default=0.0001, gt=0, strict=True)
    steps: StrictInt = Field(default=1, ge=1, le=1000)


class RetrainConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    group_id: str = Field(min_length=1, max_length=200)
    dataset_label: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    max_rounds: StrictInt = Field(default=2, ge=2, le=100)
    enabled: StrictBool = True
    auto_enabled: StrictBool = False
    cleaning: RetrainCleaningOptions = Field(default_factory=RetrainCleaningOptions)
    learning: RetrainLearningOptions = Field(default_factory=RetrainLearningOptions)
    worker_endpoints: dict[str, str] = Field(default_factory=dict)


class RetrainCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retrain_config_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,119}$")
    drift_event_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
