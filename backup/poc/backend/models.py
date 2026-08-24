"""PoC 백엔드 API용 Pydantic DTO (Data Transfer Objects) 정의서"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    """원격/로컬 Docker 호스트 노드 등록용 모델"""
    base_url: str = Field(..., description="Docker API 접속 엔드포인트 URL (e.g. tcp://localhost:2371)")
    label: str = Field(..., description="대시보드 표시용 명칭")
    tls: bool = Field(default=False, description="TLS 보안 인증 사용 여부")


class ContainerAction(BaseModel):
    """사일로 컨테이너 원격 제어용 모델"""
    action: Literal["start", "stop", "restart"] = Field(..., description="수행할 제어 액션")


class ModelPackage(BaseModel):
    """연합 AI 모델 가입소 등록용 모델"""
    model_name: str = Field(..., description="글로벌 모델 명칭")
    version: str = Field(..., description="모델 버전 (e.g. v1.0.0)")
    framework: str = Field(..., description="머신러닝 프레임워크 (e.g. pytorch, tensorflow)")
    description: str = Field(default="", description="상세 설명")


class ParameterPayload(BaseModel):
    """사일로 로컬 가중치 제출용 모델"""
    node_id: str = Field(..., description="가중치를 제출하는 사일로 ID")
    sample_size: int = Field(..., description="로컬 학습에 활용된 데이터 샘플 수 (nk)")
    weights: dict[str, float] = Field(..., description="로컬 가중치 딕셔너리 (키-값 구조)")


class CleaningRecipe(BaseModel):
    """데이터 원격 정제 레시피 정의용 모델"""
    recipe_name: str = Field(..., description="정제 레시피 명칭")
    operations: list[dict] = Field(..., description="수행할 정제 및 전처리 작업 리스트")
