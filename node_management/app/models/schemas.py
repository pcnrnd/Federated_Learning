"""Pydantic 모델 정의"""
from pydantic import BaseModel


class ServerConfig(BaseModel):
    id: str
    label: str
    base_url: str
    # type 필드 제거 - 역할에 따라 자동 결정됨
    # role 필드 제거 - 새로 추가하는 서버는 항상 "client"
    tls: bool = False


class ContainerAction(BaseModel):
    node_id: str
    container_id: str

