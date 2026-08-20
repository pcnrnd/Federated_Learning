"""POST 엔드포인트 멱등성 키 저장소 (인메모리)

X-Idempotency-Key 헤더로 동일 요청 재시도 시 캐시된 응답을 반환한다.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

_lock = threading.Lock()
_store: dict[str, _IdempotencyRecord] = {}


@dataclass
class _IdempotencyRecord:
    endpoint: str
    payload_hash: str
    status_code: int
    body: dict[str, Any]


def _hash_payload(payload: Any) -> str:
    """요청 본문의 안정적 해시를 계산한다."""
    if hasattr(payload, "model_dump"):
        raw = payload.model_dump(mode="json")
    elif isinstance(payload, dict):
        raw = payload
    else:
        raw = {"value": str(payload)}
    encoded = json.dumps(raw, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def begin(
    key: str | None,
    endpoint: str,
    payload: Any,
) -> tuple[bool, dict[str, Any] | None, int | None]:
    """멱등성 키를 검사한다.

    Returns:
        (is_new, cached_body, cached_status) — is_new=True면 신규 요청.
    """
    if not key:
        return True, None, None

    payload_hash = _hash_payload(payload)
    with _lock:
        existing = _store.get(key)
        if existing is None:
            return True, None, None
        if existing.endpoint != endpoint or existing.payload_hash != payload_hash:
            raise HTTPException(
                status_code=409,
                detail="동일 멱등성 키로 다른 요청 본문을 보냈습니다",
            )
        return False, existing.body, existing.status_code


def complete(key: str | None, endpoint: str, payload: Any, status_code: int, body: Any) -> None:
    """성공 응답을 멱등성 캐시에 저장한다."""
    if not key:
        return
    if hasattr(body, "model_dump"):
        serialized = body.model_dump(mode="json")
    elif isinstance(body, dict):
        serialized = body
    else:
        serialized = {"result": body}
    with _lock:
        _store[key] = _IdempotencyRecord(
            endpoint=endpoint,
            payload_hash=_hash_payload(payload),
            status_code=status_code,
            body=serialized,
        )


def clear() -> None:
    """테스트용 캐시 초기화"""
    with _lock:
        _store.clear()
