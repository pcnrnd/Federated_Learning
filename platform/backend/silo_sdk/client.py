"""사일로 측 push 클라이언트 (urllib만 사용)"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
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


def is_transient_error(exc: BaseException) -> bool:
    """통신/작업 정책 공통 분류. 응답 본문은 재시도 판정에 쓰지 않는다."""
    if isinstance(exc, SiloClientError):
        return exc.status == 429 or 500 <= exc.status < 600
    return isinstance(exc, (TimeoutError, OSError))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _query(**params: Any) -> str:
    """None이 아닌 파라미터만 percent-encoding 해 ?a=b&c=d 문자열로 만든다 (없으면 빈 문자열)."""
    kept = {k: v for k, v in params.items() if v is not None}
    return f"?{urllib.parse.urlencode(kept)}" if kept else ""


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
                last_exc = SiloClientError(exc.code, body_text)
                if not is_transient_error(last_exc):
                    raise last_exc from exc
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
        rows_before_cleaning: int | None = None,
        rows_after_cleaning: int | None = None,
        train_rmse: float | None = None,
    ) -> dict[str, Any]:
        """파라미터 기여를 push.

        정제한 로컬 데이터로 학습했으면 정제 전후 행 수와 학습 RMSE를 함께 보낸다(통계만).
        지정하지 않으면 payload는 기존과 같다.

        엣지 집계자가 대리 제출할 때는 `edge.combine([자신, *하위])` 결과와 함께
        `aggregated_from`에 **하위 노드 id 목록만** 넘긴다 (id 목록일 뿐 원시 데이터 아님).
        즉 `sample_count`는 **집계자 자신 + 하위**의 표본 합이고, `aggregated_from`은
        provenance 이므로 하위만 담는다 — 자기 자신을 넣으면 서버가 422로 거부한다.
        평면 제출이면 생략 — 빈 목록으로 나가 기존 동작과 동일하다.
        """
        payload: dict[str, Any] = {
            "round_id": round_id,
            "silo_id": self.silo_id,
            "sample_count": int(sample_count),
            "parameters": [float(v) for v in parameters],
            "checksum": checksum,
            "aggregated_from": list(aggregated_from or []),
        }
        stats = {"rows_before_cleaning": rows_before_cleaning,
                 "rows_after_cleaning": rows_after_cleaning, "train_rmse": train_rmse}
        payload.update({k: v for k, v in stats.items() if v is not None})
        return self._request(
            "POST",
            f"/api/training-rounds/{round_id}/contributions",
            payload,
            idempotency_key=idempotency_key,
        )

    def get_round(self, round_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/training-rounds/{round_id}")

    def list_rounds(
        self,
        *,
        status: str | None = None,
        model_name: str | None = None,
    ) -> list[Any]:
        """학습 라운드 목록 조회 — 주기 수집 워커가 open 라운드를 발견하는 데 쓴다."""
        # 모델명·상태에 공백/&/한글이 섞여도 서버가 그대로 받도록 percent-encoding 한다
        path = "/api/training-rounds" + _query(status=status or None, model_name=model_name or None)
        result = self._request("GET", path)
        return result if isinstance(result, list) else []

    def list_metrics(
        self,
        model_name: str,
        version: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Any]:
        """페이지네이션 응답에서 items만 반환한다."""
        query = _query(model_name=model_name, version=version, limit=limit, offset=offset)
        return self._request(
            "GET",
            f"/api/monitoring/metrics{query}",
            unwrap_paginated=True,
        )

    def push_resource_sample(
        self,
        cpu_pct: float | None,
        mem_pct: float | None,
        *,
        gpu_pct: float | None = None,
        disk_pct: float | None = None,
        timestamp: str | None = None,
        measurement_scope: dict[str, str] | None = None,
        unavailable: dict[str, str] | None = None,
        cpu_cores: float | None = None,
        mem_used_bytes: int | None = None,
        mem_limit_bytes: int | None = None,
        capabilities: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """리소스 사용률 스냅샷을 push (0~100 백분율)"""
        payload: dict[str, Any] = {
            "silo_id": self.silo_id,
            "cpu_pct": float(cpu_pct) if cpu_pct is not None else None,
            "mem_pct": float(mem_pct) if mem_pct is not None else None,
            "timestamp": timestamp or _now_iso(),
            "measurement_scope": measurement_scope or {},
            "unavailable": unavailable or {},
            "cpu_cores": cpu_cores,
            "mem_used_bytes": mem_used_bytes,
            "mem_limit_bytes": mem_limit_bytes,
            "capabilities": capabilities or {},
        }
        if gpu_pct is not None:
            payload["gpu_pct"] = float(gpu_pct)
        if disk_pct is not None:
            payload["disk_pct"] = float(disk_pct)
        return self._request("POST", "/api/resources/samples", payload)

    def get_silo(self) -> dict[str, Any]:
        return self._request("GET", f"/api/silos/{self.silo_id}")

    def fetch_cleaning_recipe(self, name: str, version: str) -> dict[str, Any]:
        return self._request("GET", f"/api/cleaning-recipes/{name}/{version}")

    def list_assigned_shards(self, status: str | None = "pending") -> list[Any]:
        """내게 배정된 정제 샤드 (기본: 대기 중) — 작업 번호 없이 할 일을 찾는다."""
        result = self._request(
            "GET", "/api/cleaning-shards" + _query(silo_id=self.silo_id, status=status)
        )
        return result if isinstance(result, list) else []

    def get_cleaning_job(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/cleaning-jobs/{job_id}")

    def start_cleaning_shard(self, job_id: str, shard_index: int,
                             claim_id: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/cleaning-jobs/{job_id}/shards/{shard_index}/start",
            {"silo_id": self.silo_id, "claim_id": claim_id},
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
        schema_fingerprint: str | None = None,
        attempt_id: str | None = None,
        retryable: bool = False,
        output_id: str | None = None,
        output_hash: str | None = None,
        source_hash: str | None = None,
        recipe_hash: str | None = None,
    ) -> dict[str, Any]:
        """정제 샤드 처리 결과 보고 — 통계만, 원시 데이터 없음.

        schema_fingerprint: 정제 결과의 공통 스키마 지문(sha256) — 서버가 사일로 간 일치를 판정.
        """
        payload: dict[str, Any] = {
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
        if schema_fingerprint is not None:
            payload["schema_fingerprint"] = schema_fingerprint
        payload.update(attempt_id=attempt_id, retryable=retryable, output_id=output_id,
                       output_hash=output_hash, source_hash=source_hash, recipe_hash=recipe_hash)
        return self._request(
            "POST",
            f"/api/cleaning-jobs/{job_id}/shards/{shard_index}/report",
            payload,
        )

    def cleaning_progress(self, job_id: str, shard_index: int, attempt_id: str,
                          processed_units: int, total_units: int, stage: str) -> dict[str, Any]:
        return self._request("POST", f"/api/cleaning-jobs/{job_id}/shards/{shard_index}/progress",
            {"silo_id": self.silo_id, "attempt_id": attempt_id, "processed_units": processed_units,
             "total_units": total_units, "stage": stage})

    # ---------- 사일로 간 수직 정렬 (HMAC 다이제스트만 — 원본 id 없음) ----------

    def submit_alignment_keys(self, alignment_id: str, hashed_keys: list[str]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/alignment-jobs/{alignment_id}/submit",
            {"silo_id": self.silo_id, "hashed_keys": list(hashed_keys)},
        )

    def get_alignment(self, alignment_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/alignment-jobs/{alignment_id}")

    def get_alignment_intersection(self, alignment_id: str) -> dict[str, Any]:
        """교집합 다이제스트 — 다른 사일로가 아직 제출 전이면 SiloClientError(409)."""
        return self._request(
            "GET",
            f"/api/alignment-jobs/{alignment_id}/intersection" + _query(silo_id=self.silo_id),
        )

    def report_alignment(
        self, alignment_id: str, matched: int, excluded: int, order_digest: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/alignment-jobs/{alignment_id}/report",
            {"silo_id": self.silo_id, "matched": int(matched), "excluded": int(excluded),
             "order_digest": order_digest},
        )

    def health(self) -> bool:
        """간단한 ping — 메인 페이지로 200 응답 확인"""
        try:
            self._request("GET", "/")
            return True
        except Exception:  # noqa: BLE001
            return False
