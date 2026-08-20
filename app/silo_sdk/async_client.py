"""비동기 사일로 SDK 클라이언트 — 다수 사일로/메트릭 push 시 동시성 향상.

내부적으로는 기존 SiloClient를 `asyncio.to_thread`로 호출 — 외부 의존성 추가 없음.
다수 push 동시 수행 시 `asyncio.gather`로 wall-clock 감소.
"""
from __future__ import annotations

import asyncio
from typing import Any, Literal

from .client import SiloClient

MetricName = Literal["accuracy", "latency_ms", "throughput_rps"]


class AsyncSiloClient:
    def __init__(
        self,
        base_url: str,
        silo_id: str,
        *,
        timeout: float = 10.0,
        retries: int = 3,
        api_key: str | None = None,
    ) -> None:
        self._sync = SiloClient(
            base_url,
            silo_id,
            timeout=timeout,
            retries=retries,
            api_key=api_key,
        )

    @property
    def silo_id(self) -> str:
        return self._sync.silo_id

    async def push_metric(
        self,
        model_name: str,
        version: str,
        metric: MetricName,
        value: float,
        *,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._sync.push_metric, model_name, version, metric, value, timestamp=timestamp
        )

    async def push_distribution(
        self,
        model_name: str,
        version: str,
        feature: str,
        bin_edges: list[float],
        bin_counts: list[int],
        *,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._sync.push_distribution,
            model_name,
            version,
            feature,
            bin_edges,
            bin_counts,
            timestamp=timestamp,
        )

    async def push_parameters(
        self,
        round_id: str,
        sample_count: int,
        parameters: list[float],
        *,
        checksum: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._sync.push_parameters,
            round_id,
            sample_count,
            parameters,
            checksum=checksum,
            idempotency_key=idempotency_key,
        )

    async def push_resource_sample(
        self,
        cpu_pct: float,
        mem_pct: float,
        *,
        gpu_pct: float | None = None,
        disk_pct: float | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._sync.push_resource_sample,
            cpu_pct,
            mem_pct,
            gpu_pct=gpu_pct,
            disk_pct=disk_pct,
            timestamp=timestamp,
        )

    async def push_many_metrics(
        self,
        samples: list[tuple[str, str, MetricName, float]],
    ) -> list[dict[str, Any]]:
        """여러 (model, version, metric, value)를 병렬 push — 다중 보고 시 가장 큰 이득"""
        coros = [self.push_metric(m, v, k, val) for (m, v, k, val) in samples]
        return list(await asyncio.gather(*coros))

    async def get_round(self, round_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync.get_round, round_id)

    async def list_metrics(
        self,
        model_name: str,
        version: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Any]:
        """페이지네이션 응답에서 items만 반환한다."""
        return await asyncio.to_thread(
            self._sync.list_metrics,
            model_name,
            version,
            limit=limit,
            offset=offset,
        )
