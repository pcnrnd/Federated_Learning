"""사일로 측 push 클라이언트 (urllib만 사용)"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Literal

logger = logging.getLogger(__name__)

MetricName = Literal["accuracy", "latency_ms", "throughput_rps"]


class SiloClientError(Exception):
    """SDK 호출 실패. 상태 코드와 본문을 포함한다."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unwrap_paginated(body: dict[str, Any]) -> list[Any]:
    """PaginatedResponse({items, total, ...})이면 items 리스트만 반환한다."""
    if "items" in body and "total" in body:
        return list(body["items"])
    return []


class SiloClient:
    """경량 push 클라이언트.

    Args:
        base_url: 중앙 대시보드 URL (예: http://central:8000)
        silo_id: 본 사일로의 식별자 — servers.yaml의 노드 ID와 일치해야 함.
        timeout: HTTP 타임아웃 (초)
        retries: 재시도 횟수 (지수 백오프)
    """

    def __init__(
        self,
        base_url: str,
        silo_id: str,
        *,
        timeout: float = 10.0,
        retries: int = 3,
        api_key: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.silo_id = silo_id
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.api_key = api_key or os.getenv("FED_API_KEY") or None

    # ---------- 내부 ----------

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        unwrap_paginated: bool = False,
    ) -> dict[str, Any] | list[Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url=url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        if self.api_key:
            req.add_header("X-FED-API-Key", self.api_key)
        if idempotency_key:
            req.add_header("X-Idempotency-Key", idempotency_key)

        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    if not raw:
                        return [] if unwrap_paginated else {}
                    parsed = json.loads(raw)
                    if unwrap_paginated and isinstance(parsed, dict):
                        return _unwrap_paginated(parsed)
                    return parsed
            except urllib.error.HTTPError as exc:
                body_text = exc.read().decode("utf-8", errors="replace")
                if 400 <= exc.code < 500:
                    raise SiloClientError(exc.code, body_text) from exc
                last_exc = SiloClientError(exc.code, body_text)
            except (urllib.error.URLError, TimeoutError) as exc:
                last_exc = exc
            if attempt < self.retries:
                backoff = 0.5 * (2 ** attempt)
                logger.warning("push 재시도 %d → %s (대기 %.1fs)", attempt + 1, url, backoff)
                time.sleep(backoff)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("unreachable")

    # ---------- 공개 API ----------

    def push_metric(
        self,
        model_name: str,
        version: str,
        metric: MetricName,
        value: float,
        *,
        timestamp: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "node_id": self.silo_id,
            "model_name": model_name,
            "version": version,
            "metric": metric,
            "value": float(value),
            "timestamp": timestamp or _now_iso(),
        }
        return self._request(
            "POST",
            "/api/monitoring/metrics",
            payload,
            idempotency_key=idempotency_key,
        )

    def push_distribution(
        self,
        model_name: str,
        version: str,
        feature: str,
        bin_edges: list[float],
        bin_counts: list[int],
        *,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """히스토그램만 push — 원시 값 ❌"""
        payload = {
            "node_id": self.silo_id,
            "model_name": model_name,
            "version": version,
            "feature": feature,
            "bin_edges": list(bin_edges),
            "bin_counts": list(bin_counts),
            "timestamp": timestamp or _now_iso(),
        }
        return self._request("POST", "/api/monitoring/drift", payload)

    def push_parameters(
        self,
        round_id: str,
        sample_count: int,
        parameters: list[float],
        *,
        checksum: str | None = None,
        idempotency_key: str | None = None,
        aggregated_from: list[str] | None = None,
    ) -> dict[str, Any]:
        """파라미터 기여를 push.

        엣지 집계자가 하위를 대리 제출할 때는 `edge.combine()` 결과와 함께
        `aggregated_from`에 하위 노드 id 목록을 넘긴다 (id 목록일 뿐 원시 데이터 아님).
        평면 제출이면 생략 — 빈 목록으로 나가 기존 동작과 동일하다.
        """
        payload = {
            "round_id": round_id,
            "silo_id": self.silo_id,
            "sample_count": int(sample_count),
            "parameters": [float(v) for v in parameters],
            "checksum": checksum,
            "aggregated_from": list(aggregated_from or []),
        }
        return self._request(
            "POST",
            f"/api/training-rounds/{round_id}/contributions",
            payload,
            idempotency_key=idempotency_key,
        )

    def get_round(self, round_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/training-rounds/{round_id}")

    def list_metrics(
        self,
        model_name: str,
        version: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Any]:
        """페이지네이션 응답에서 items만 반환한다."""
        query = (
            f"?model_name={model_name}&version={version}"
            f"&limit={limit}&offset={offset}"
        )
        return self._request(
            "GET",
            f"/api/monitoring/metrics{query}",
            unwrap_paginated=True,
        )

    def push_resource_sample(
        self,
        cpu_pct: float,
        mem_pct: float,
        *,
        gpu_pct: float | None = None,
        disk_pct: float | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """리소스 사용률 스냅샷을 push (0~100 백분율)"""
        payload: dict[str, Any] = {
            "silo_id": self.silo_id,
            "cpu_pct": float(cpu_pct),
            "mem_pct": float(mem_pct),
            "timestamp": timestamp or _now_iso(),
        }
        if gpu_pct is not None:
            payload["gpu_pct"] = float(gpu_pct)
        if disk_pct is not None:
            payload["disk_pct"] = float(disk_pct)
        return self._request("POST", "/api/resources/samples", payload)

    def fetch_cleaning_recipe(self, name: str, version: str) -> dict[str, Any]:
        return self._request("GET", f"/api/cleaning-recipes/{name}/{version}")

    def start_cleaning_shard(self, job_id: str, shard_index: int) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/cleaning-jobs/{job_id}/shards/{shard_index}/start",
            {"silo_id": self.silo_id},
        )

    def report_cleaning_shard(
        self,
        job_id: str,
        shard_index: int,
        rows_in: int,
        rows_out: int,
        step_counters: dict[str, int],
        *,
        started_at: str | None = None,
        completed_at: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """정제 샤드 처리 결과 보고 — 통계만, 원시 데이터 없음."""
        payload = {
            "job_id": job_id,
            "shard_index": shard_index,
            "silo_id": self.silo_id,
            "rows_in": int(rows_in),
            "rows_out": int(rows_out),
            "step_counters": dict(step_counters),
            "started_at": started_at or _now_iso(),
            "completed_at": completed_at or _now_iso(),
            "error": error,
        }
        return self._request(
            "POST",
            f"/api/cleaning-jobs/{job_id}/shards/{shard_index}/report",
            payload,
        )

    def health(self) -> bool:
        """간단한 ping — 메인 페이지로 200 응답 확인"""
        try:
            self._request("GET", "/")
            return True
        except Exception:  # noqa: BLE001
            return False
