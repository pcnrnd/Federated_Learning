"""지속 pull/admission과 취소 가능한 attempt 전용 정제 프로세스."""
from __future__ import annotations

import asyncio
import json
import signal
import sys
import time
import uuid

from .client import SiloClient, SiloClientError, is_transient_error


class ExecutionCleanupError(RuntimeError):
    """실제 실행 종료 미확인 시 worker 전체의 신규 admission을 멈춘다."""


class CleaningProcessError(RuntimeError):
    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


def _executor_command() -> list[str]:
    return [sys.executable, "-u", "-m", "silo_sdk.cleaning_executor"]


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()  # 해당 attempt가 만든 단일 PID. 손자 process는 만들지 않는다.
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=1)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
        except asyncio.TimeoutError as exc:
            raise ExecutionCleanupError("정제 실행 프로세스 종료를 확인하지 못했습니다") from exc


async def _execute(client, job, shard, recipe, data_dir, timeout):
    launched_at = time.monotonic()
    process = await asyncio.create_subprocess_exec(*_executor_command(),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)

    async def exchange():
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({"data_dir": data_dir, "silo_id": client.silo_id,
            "job": job, "shard": shard, "recipe": recipe}).encode("ascii"))
        await process.stdin.drain()
        process.stdin.close()
        result, error = None, None
        while line := await process.stdout.readline():
            message = json.loads(line)
            if message["type"] == "progress":
                await asyncio.to_thread(client.cleaning_progress, job["job_id"], shard["shard_index"],
                    shard["attempt_id"], message["done"], message["total"], message["stage"])
            elif message["type"] == "result":
                result = message["manifest"]
            elif message["type"] == "error":
                error = CleaningProcessError(message["message"], message["retryable"])
        exit_code = await process.wait()
        if error:
            raise error
        if exit_code != 0 or result is None:
            raise CleaningProcessError("정제 프로세스가 성공 결과 없이 종료되었습니다", True)
        return result

    try:
        return await asyncio.wait_for(exchange(), timeout=max(0, timeout - (time.monotonic() - launched_at)))
    finally:
        await _stop_process(process)  # 실제 종료 확인 뒤에만 호출자의 실행 슬롯 반납.


async def _failure(client, job_id, index, shard, message, retryable):
    try:
        await asyncio.to_thread(client.report_cleaning_shard, job_id, index,
            rows_in=0, rows_out=0, step_counters={}, error=message,
            attempt_id=shard["attempt_id"], retryable=retryable)
    except (OSError, SiloClientError):
        pass  # 연결 실패 시 중앙의 persisted deadline sweep가 정리한다.


async def process_assignment(client: SiloClient, assignment: dict, data_dir: str,
                             executor=None) -> bool:
    """executor 인자는 이전 단발 호출 호환용이며 CPU thread 실행에는 사용하지 않는다."""
    job_id, index = assignment["job_id"], assignment["shard_index"]
    claimed_at = time.monotonic()
    try:
        job = await asyncio.to_thread(client.start_cleaning_shard, job_id, index, uuid.uuid4().hex)
    except SiloClientError as exc:
        if exc.status in (404, 409):
            return False
        raise
    shard = job["shards"][index]
    try:
        recipe = await asyncio.to_thread(client.fetch_cleaning_recipe, job["recipe_name"], job["recipe_version"])
        remaining = job["timeout_seconds"] - (time.monotonic() - claimed_at)
        if remaining <= 0:
            raise asyncio.TimeoutError()
        manifest = await _execute(client, job, shard, recipe, data_dir, remaining)
        fields = {key: manifest[key] for key in ("rows_in", "rows_out", "step_counters", "schema_fingerprint",
                                                 "output_id", "output_hash", "source_hash", "recipe_hash")}
        await asyncio.to_thread(client.report_cleaning_shard, job_id, index, **fields,
                                attempt_id=shard["attempt_id"], started_at=shard["started_at"])
        return True
    except asyncio.CancelledError:
        await _failure(client, job_id, index, shard, "정제 worker 실행 취소", True)
        raise
    except ExecutionCleanupError:
        raise  # 자원 회수 미확인 상태에서 같은 worker가 새 작업을 claim하지 않는다.
    except Exception as exc:  # noqa: BLE001
        transient = exc.retryable if isinstance(exc, CleaningProcessError) else (
            isinstance(exc, asyncio.TimeoutError) or is_transient_error(exc))
        message = str(exc) if isinstance(exc, CleaningProcessError) else f"로컬 정제 실행 실패: {type(exc).__name__}"
        await _failure(client, job_id, index, shard, message, transient)
        return False


async def cycle(client: SiloClient, data_dir: str, executor=None, concurrency: int = 2) -> list[bool]:
    """명시적인 단발 호출만 위한 helper. 지속 worker는 아래 독립 poll loop를 사용한다."""
    assignments = await asyncio.to_thread(client.list_assigned_shards, "pending")
    semaphore = asyncio.Semaphore(max(1, min(concurrency, 4)))

    async def one(assignment):
        async with semaphore:
            return await process_assignment(client, assignment, data_dir)

    return await asyncio.gather(*(one(a) for a in assignments))


async def run(client: SiloClient, data_dir: str, poll_interval: float = 2,
              concurrency: int = 2, max_cycles: int = 0) -> None:
    active: dict[tuple, asyncio.Task] = {}
    limit, count = max(1, min(concurrency, 4)), 0
    try:
        while max_cycles == 0 or count < max_cycles:
            for key, task in list(active.items()):
                if task.done():
                    del active[key]
                    try:
                        task.result()
                    except (OSError, SiloClientError):
                        pass
            if len(active) < limit:
                try:
                    assignments = await asyncio.to_thread(client.list_assigned_shards, "pending")
                except (OSError, SiloClientError):
                    assignments = []
                for assignment in assignments:
                    key = (assignment["job_id"], assignment["shard_index"], assignment.get("generation", 0))
                    if key not in active and len(active) < limit:
                        active[key] = asyncio.create_task(process_assignment(client, assignment, data_dir))
            count += 1
            if max_cycles == 0 or count < max_cycles:
                await asyncio.sleep(max(0.01, poll_interval))
        await asyncio.gather(*active.values())
    finally:
        for task in active.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*active.values(), return_exceptions=True)


def run_with_signals(client: SiloClient, data_dir: str, poll_interval: float = 2,
                     concurrency: int = 2, max_cycles: int = 0) -> None:
    """CLI의 TERM/INT를 같은 async 취소·child 회수 경로에 연결한다."""
    async def serve():
        loop = asyncio.get_running_loop()
        worker = asyncio.create_task(run(client, data_dir, poll_interval, concurrency, max_cycles))
        stopping = False
        def stop(_signum, _frame):
            nonlocal stopping
            if stopping:
                return
            stopping = True
            loop.call_soon_threadsafe(worker.cancel)
        previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            await worker
        except asyncio.CancelledError:
            if not stopping:
                raise
        finally:
            if not worker.done():
                worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    asyncio.run(serve())
