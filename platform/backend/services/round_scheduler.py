"""주기 수집 스케줄러 — 라운드 상태를 주기적으로 점검하고 조건 충족 시 자동 집계.

FastAPI lifespan과 결합해 asyncio.Task로 동작한다.
사일로는 SDK 또는 직접 POST로 기여를 push하고, 스케줄러는 단순히 충분히 모인 라운드를 자동 집계한다.
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import HTTPException

from config.federated_manager import load_contributions
from services import deployment_service, training_job_service, training_round_service

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_SECONDS = 15.0


def _env_interval() -> float:
    """FED_SCHEDULER_INTERVAL(초) — 연속 라운드 실측 등에서 tick 간격 단축용."""
    raw = os.getenv("FED_SCHEDULER_INTERVAL", "")
    if not raw:
        return _DEFAULT_INTERVAL_SECONDS
    try:
        return float(raw)
    except ValueError:
        logger.warning("FED_SCHEDULER_INTERVAL 값이 숫자가 아님 (%r) — 기본 %.0fs 사용",
                       raw, _DEFAULT_INTERVAL_SECONDS)
        return _DEFAULT_INTERVAL_SECONDS


class RoundScheduler:
    """주기 백그라운드 수집/집계 스케줄러"""

    def __init__(self, interval_seconds: float | None = None) -> None:
        chosen = _env_interval() if interval_seconds is None else float(interval_seconds)
        self._interval = max(1.0, chosen)
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None

    @property
    def interval(self) -> float:
        return self._interval

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._loop(), name="round-scheduler")
        logger.info("RoundScheduler 시작 (interval=%.1fs)", self._interval)

    async def stop(self) -> None:
        if not self.running or self._stop_event is None or self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=self._interval + 5.0)
        except asyncio.TimeoutError:
            self._task.cancel()
        finally:
            self._task = None
            self._stop_event = None
            logger.info("RoundScheduler 정지")

    def _tick_blocking(self) -> list[str]:
        """tick의 동기 본체 — 저장소 I/O를 포함하므로 이벤트 루프에서 직접 부르지 않는다."""
        aggregated_ids: list[str] = []
        open_rounds = training_round_service.list_rounds(status="open")
        contributions = load_contributions()
        for entry in open_rounds:
            count = len(contributions.get(entry.round_id, {}))
            if count >= entry.min_contributions:
                try:
                    training_round_service.aggregate_round(entry.round_id)
                    aggregated_ids.append(entry.round_id)
                except HTTPException as exc:
                    logger.warning(
                        "라운드 %s 집계 실패: %s",
                        entry.round_id,
                        exc.detail,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error("라운드 %s 집계 예외: %s", entry.round_id, exc)
        return aggregated_ids

    async def tick(self) -> list[str]:
        """단일 tick — 집계 가능한 라운드를 모두 집계하고 라운드 ID 목록을 반환한다.

        저장소 이력이 커지면 tick이 수 초까지 길어진다 — 이벤트 루프를 잡아두면
        모든 HTTP 응답이 밀려 사일로 push가 타임아웃되므로 스레드로 위임한다 (실측).
        """
        return await asyncio.to_thread(self._tick_blocking)

    async def tick_jobs(self) -> list[str]:
        """잡 스케줄러 단일 tick — active 잡들의 다음 라운드를 트리거한다."""
        try:
            return await asyncio.to_thread(training_job_service.tick)
        except Exception as exc:  # noqa: BLE001
            logger.error("잡 tick 오류: %s", exc)
            return []

    async def _loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                # 1. 충분히 모인 라운드 집계 (잡 reconcile 전에 수행해야 카운터 정확)
                await self.tick()
                # 2. 잡 진행 — 완료된 라운드 reconcile + 다음 라운드 open
                await self.tick_jobs()
                # 3. running/pending 배포 상태를 Docker 실제 상태와 동기화
                try:
                    await asyncio.to_thread(deployment_service.reconcile_all_active)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("배포 reconcile 실패: %s", exc)
            except Exception as exc:  # noqa: BLE001
                logger.error("스케줄러 tick 오류: %s", exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue


_scheduler = RoundScheduler()


def get_scheduler() -> RoundScheduler:
    return _scheduler
