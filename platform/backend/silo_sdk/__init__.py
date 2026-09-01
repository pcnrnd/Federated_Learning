"""Federated Learning 사일로 SDK

사일로 측에서 import해 중앙 대시보드(`backup/node_management_v0,2`)로 메트릭/분포통계/
파라미터 기여를 push하는 경량 클라이언트.

설계 원칙:
  * 원시 데이터를 절대 전송하지 않는다.
  * 표준 라이브러리만 사용 (urllib) — 사일로 환경 의존성 최소화.
  * push 실패 시 호출 측이 결정할 수 있도록 예외를 그대로 전파.
"""
from . import edge
from .async_client import AsyncSiloClient
from .cleaning import apply_recipe
from .client import SiloClient, SiloClientError
from .edge import combine
from .histograms import build_histogram
from .trainer import RidgeResult, train_ridge

__all__ = [
    "AsyncSiloClient",
    "RidgeResult",
    "SiloClient",
    "SiloClientError",
    "apply_recipe",
    "build_histogram",
    "combine",
    "edge",
    "train_ridge",
]
