"""사일로 간 수직 정렬 — 공유 키 HMAC 교집합 (표준 라이브러리 전용).

흐름:
  1. 사일로는 공유 키 `FED_ALIGN_KEY`(사일로 환경변수 — 서버에는 두지 않는다)로
     엔터티 id마다 HMAC-SHA256 다이제스트를 만들어 다이제스트 목록만 서버에 보낸다.
  2. 서버는 참여 사일로들의 다이제스트 교집합을 정렬해 돌려준다.
  3. 사일로는 교집합 엔터티만 그 순서대로 남긴다 → 모든 사일로가 같은 엔터티를 같은 순서로 가진다.

원본 id와 원본 행은 사일로 밖으로 나가지 않는다. 서버는 키가 없어 다이제스트를 id로 되돌릴 수
없다. 한계: 키를 사일로끼리 공유하므로 한 사일로가 다른 사일로의 다이제스트를 추측 가능한 id
사전으로 대조할 수 있고, 서버는 교집합 크기와 어떤 다이제스트가 공통인지 안다. 이를 막으려면
키 공유 없는 PSI(사설 교집합 — ECDH·OPRF 기반)로 바꿔야 한다 (docs/silo-sdk-guide.md).
"""
from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Iterable, Mapping
from typing import Any

ALIGN_KEY_ENV = "FED_ALIGN_KEY"
MIN_KEY_LENGTH = 16

Row = dict[str, Any]


def load_align_key(env: Mapping[str, str] | None = None) -> bytes:
    """사일로 환경변수의 공유 키. 없거나 짧으면 ValueError."""
    key = (os.environ if env is None else env).get(ALIGN_KEY_ENV, "")
    if len(key) < MIN_KEY_LENGTH:
        raise ValueError(
            f"{ALIGN_KEY_ENV}(사일로 공유 키, {MIN_KEY_LENGTH}자 이상)가 사일로 환경변수에 필요합니다"
        )
    return key.encode("utf-8")


def _digest(entity_id: Any, key: bytes) -> str:
    return hmac.new(key, str(entity_id).encode("utf-8"), hashlib.sha256).hexdigest()


def hash_ids(ids: Iterable[Any], key: bytes) -> dict[str, Any]:
    """id → HMAC-SHA256 hex. 반환은 {다이제스트: id} (같은 id는 한 번만) — 다이제스트만 보낸다."""
    return {_digest(entity_id, key): entity_id for entity_id in ids}


def order_digest(hashed_keys: list[str]) -> str:
    """정렬 순서 지문 — 사일로들이 같은 순서를 가졌는지 서버가 비교한다 (값 없이 순서만)."""
    return hashlib.sha256("\n".join(hashed_keys).encode("utf-8")).hexdigest()


def align_rows(
    rows: list[Row], key_column: str, intersection: list[str], key: bytes
) -> tuple[list[Row], dict[str, Any]]:
    """교집합 엔터티만 서버가 준 순서대로 남긴다. (정렬된 행, 통계)

    통계: submitted(내 엔터티 수), matched(남은 수), excluded(제외 수), order_digest.
    """
    by_digest: dict[str, Row] = {}
    for row in rows:
        by_digest.setdefault(_digest(row[key_column], key), row)
    kept_keys = [d for d in intersection if d in by_digest]
    aligned = [by_digest[d] for d in kept_keys]
    return aligned, {
        "submitted": len(by_digest),
        "matched": len(aligned),
        "excluded": len(by_digest) - len(aligned),
        "order_digest": order_digest(kept_keys),
    }
