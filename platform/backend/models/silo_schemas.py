"""실제 사일로 등록 계약 — 로컬 원천 데이터나 인증 정보는 받지 않는다."""
from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


class SiloRegisterRequest(BaseModel):
    silo_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    label: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=300)
    collect_interval_seconds: int = Field(default=15, ge=5, le=86400)

    @field_validator("label", "base_url")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("빈 값은 등록할 수 없습니다")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        if not value.startswith(("tcp://", "unix://", "http://", "https://")) or "@" in value:
            raise ValueError("인증 정보를 포함하지 않은 Docker 엔드포인트가 필요합니다")
        parsed = urlsplit(value)
        if parsed.query or parsed.fragment:
            raise ValueError("엔드포인트에 query 또는 fragment를 포함할 수 없습니다")
        if parsed.scheme == "unix":
            if not parsed.path.startswith("/"):
                raise ValueError("Unix socket의 절대 경로가 필요합니다")
        elif not parsed.hostname or (parsed.scheme == "tcp" and parsed.port is None):
            raise ValueError("유효한 호스트와 TCP 포트가 필요합니다")
        elif parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("유효한 TCP 포트가 필요합니다")
        return value


class SiloRegistration(BaseModel):
    silo_id: str
    label: str
    base_url: str
    collect_interval_seconds: int = 15
