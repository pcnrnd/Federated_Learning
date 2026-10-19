"""지속 pull worker: 비동기 I/O와 제한된 로컬 정제 실행. 외부 패키지 불필요."""
from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import cleaning_output
from .client import SiloClient, SiloClientError
from .integration import CleaningError


async def process_assignment(client: SiloClient, assignment: dict, data_dir: str,
                             executor: ThreadPoolExecutor) -> bool:
    job_id, index = assignment["job_id"], assignment["shard_index"]
    try:
        job = await asyncio.to_thread(client.start_cleaning_shard, job_id, index, uuid.uuid4().hex)
    except SiloClientError as exc:
        if exc.status == 409:
            return False  # 다른 worker가 먼저 claim 또는 의존/시각 변경. 실행하지 않는다.
        raise
    shard = job["shards"][index]
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    progress_open = True

    async def publish():
        while (item := await queue.get()) is not None:
            done, total, stage = item
            await asyncio.to_thread(client.cleaning_progress, job_id, index, shard["attempt_id"],
                                    done, total, stage)

    def progress(done, total, stage):
        if progress_open:
            loop.call_soon_threadsafe(queue.put_nowait, (done, total, stage))

    reporter = asyncio.create_task(publish())
    try:
        recipe = await asyncio.to_thread(client.fetch_cleaning_recipe, job["recipe_name"], job["recipe_version"])
        work = loop.run_in_executor(executor, cleaning_output.execute,
            data_dir, client.silo_id, job, shard, recipe, progress)
        work.add_done_callback(lambda finished: finished.exception() if not finished.cancelled() else None)
        manifest = await asyncio.wait_for(asyncio.shield(work), timeout=job["timeout_seconds"])
        await queue.put(None)
        await reporter
        fields = {key: manifest[key] for key in ("rows_in", "rows_out", "step_counters", "schema_fingerprint",
                                                 "output_id", "output_hash", "source_hash", "recipe_hash")}
        await asyncio.to_thread(client.report_cleaning_shard, job_id, index, **fields,
                                attempt_id=shard["attempt_id"], started_at=shard["started_at"])
        return True
    except asyncio.CancelledError:
        reporter.cancel()
        await asyncio.gather(reporter, return_exceptions=True)
        try:
            await asyncio.to_thread(client.report_cleaning_shard, job_id, index,
                rows_in=0, rows_out=0, step_counters={}, error="정제 worker 실행 취소",
                attempt_id=shard["attempt_id"], retryable=True)
        except (OSError, SiloClientError):
            pass
        raise
    except Exception as exc:  # noqa: BLE001
        reporter.cancel()
        await asyncio.gather(reporter, return_exceptions=True)
        # 원천 값이나 exception의 원시 행/경로를 로그·중앙 오류에 복사하지 않는다.
        error = str(exc)[:500] if isinstance(exc, CleaningError) else f"로컬 정제 실행 실패: {type(exc).__name__}"
        try:
            await asyncio.to_thread(client.report_cleaning_shard, job_id, index,
                rows_in=0, rows_out=0, step_counters={}, error=error,
                attempt_id=shard["attempt_id"], retryable=isinstance(exc, (OSError, TimeoutError, SiloClientError)))
        except (OSError, SiloClientError):
            pass  # 중앙 deadline sweep가 실행권한을 정리한다.
        return False
    finally:
        progress_open = False


async def cycle(client: SiloClient, data_dir: str, executor: ThreadPoolExecutor,
                concurrency: int = 2) -> list[bool]:
    assignments = await asyncio.to_thread(client.list_assigned_shards, "pending")
    semaphore = asyncio.Semaphore(max(1, min(concurrency, 4)))

    async def one(assignment):
        async with semaphore:
            return await process_assignment(client, assignment, data_dir, executor)

    return await asyncio.gather(*(one(a) for a in assignments))


async def run(client: SiloClient, data_dir: str, poll_interval: float = 2,
              concurrency: int = 2, max_cycles: int = 0) -> None:
    count = 0
    with ThreadPoolExecutor(max_workers=max(1, min(concurrency, 4))) as executor:
        while max_cycles == 0 or count < max_cycles:
            try:
                await cycle(client, data_dir, executor, concurrency)
            except (OSError, SiloClientError):
                pass  # 연결 복구 후 persisted pending을 다시 찾는다.
            count += 1
            if max_cycles == 0 or count < max_cycles:
                await asyncio.sleep(max(0.1, poll_interval))
