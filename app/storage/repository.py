"""도메인 dict 영속화용 Repository 인터페이스."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DictRepository(Protocol):
    """YAML/SQLite 공통 — 최상위 dict(id → payload) 또는 중첩 models dict."""

    def load(self) -> dict[str, Any]:
        """전체 도메인 스냅샷을 로드한다."""
        ...

    def save(self, data: dict[str, Any]) -> None:
        """전체 도메인 스냅샷을 원자적으로 저장한다."""
        ...
