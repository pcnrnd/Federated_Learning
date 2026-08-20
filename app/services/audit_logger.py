"""감사 로그 — 모니터링 이벤트의 영구 기록"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from config.monitoring_manager import append_audit, read_audit


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(event_type: str, **fields: Any) -> None:
    """JSON Lines 형식으로 한 줄 추가"""
    payload = {"ts": _now_iso(), "event": event_type, **fields}
    append_audit(json.dumps(payload, ensure_ascii=False))


def tail(n: int = 100) -> list[dict[str, Any]]:
    """최근 n개 감사 로그를 dict 리스트로 반환"""
    lines = read_audit(tail=n)
    out: list[dict[str, Any]] = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"raw": line})
    return out
