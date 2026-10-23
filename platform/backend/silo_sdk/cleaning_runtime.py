"""지속 pull/admission과 취소 가능한 attempt 전용 정제 프로세스."""
from __future__ import annotations

import asyncio
import json
import re
import signal
import sys
import time
import uuid

from .client import SiloClient, SiloClientError, is_transient_error


class ExecutionCleanupError(RuntimeError):
    """실제 실행 종료 미확인 시 worker 전체의 신규 admission을 멈춘다."""


class TerminalAckUnknown(RuntimeError):
    """성공 보고 상태를 확인하지 못하면 재전송 없이 현재 worker admission을 멈춘다."""


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


class _Progress:
    """진행 보고는 한 요청과 최신 값 하나만 유지한다. 결과 pipe를 기다리게 하지 않는다."""

    def __init__(self, client, job, shard):
        self.client, self.job, self.shard = client, job, shard
        self.latest = None
        self.closed = False
        self.changed = asyncio.Event()
        self.task = asyncio.create_task(self.send())

    def publish(self, message):
        if not self.closed:
            self.latest = (message["done"], message["total"], message["stage"])
            self.changed.set()

    async def send(self):
        while not self.closed:
            await self.changed.wait()
            self.changed.clear()
            if self.closed:
                break
            value, self.latest = self.latest, None
            try:
                await asyncio.to_thread(self.client.cleaning_progress, self.job["job_id"],
                    self.shard["shard_index"], self.shard["attempt_id"], *value)
            except (OSError, SiloClientError, json.JSONDecodeError, UnicodeDecodeError):
                # ACK 유실 여부는 알 수 없다. 재전송하지 않고 다음 최신 진행량만 허용한다.
                pass

    async def close(self):
        self.closed = True
        self.latest = None
        self.changed.set()
        # to_thread 취소는 실제 HTTP 요청을 멈추지 않는다. 2초 단일 요청 스레드를
        # 회수한 뒤 terminal report를 보낸다. 서버에 늦게 도착한 진행은 token/running
        # 검사가 차단한다. HTTP timeout 자체를 서버의 미반영 증거로 취급하지 않는다.
        try:
            await asyncio.shield(self.task)
        except asyncio.CancelledError:
            await asyncio.shield(self.task)
            raise


async def _execute(client, job, shard, recipe, data_dir, timeout):
    launched_at = time.monotonic()
    process = await asyncio.create_subprocess_exec(*_executor_command(),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    progress = _Progress(client, job, shard)

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
                progress.publish(message)
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
        try:
            await _stop_process(process)  # 실제 종료 확인 뒤에만 호출자의 실행 슬롯 반납.
        finally:
            await progress.close()


def _ack_matches(ack, client, job, shard, fields):
    if not isinstance(ack, dict) or not isinstance(ack.get("shards"), list):
        return False
    if not all(isinstance(row, dict) for row in ack["shards"]):
        return False
    matches = [row for row in ack["shards"] if type(row.get("shard_index")) is int
               and row["shard_index"] == shard["shard_index"]]
    return (ack.get("job_id") == job["job_id"] and type(ack.get("generation")) is int
        and ack["generation"] == job["generation"]
        and len(matches) == 1 and matches[0].get("status") == "completed"
        and matches[0].get("silo_id") == client.silo_id
        and matches[0].get("attempt_id") == shard["attempt_id"]
        and all(matches[0].get(key) == value for key, value in fields.items()))


async def _reconcile_success(client, job, shard, fields):
    try:
        current = await asyncio.to_thread(client.get_cleaning_job, job["job_id"])
    except (OSError, SiloClientError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TerminalAckUnknown("정제 성공 보고 ACK·현재 상태 미확인: 신규 admission 중단") from exc
    if _ack_matches(current, client, job, shard, fields):
        return True
    if isinstance(current, dict) and current.get("job_id") == job["job_id"]:
        generation = current.get("generation")
        if type(generation) is not int or generation < job["generation"]:
            raise TerminalAckUnknown("정제 성공 보고 generation 미확인: 신규 admission 중단")
        if generation > job["generation"]:
            return False  # 명시적으로 새 generation이 이전 실행권한을 닫았다.
        rows = current.get("shards")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise TerminalAckUnknown("정제 성공 보고 현재 상태 형식 미확인: 신규 admission 중단")
        rows = [r for r in rows if type(r.get("shard_index")) is int
                and r["shard_index"] == shard["shard_index"]]
        if (len(rows) != 1 or rows[0].get("silo_id") != client.silo_id
                or not isinstance(rows[0].get("attempt_id"), str)
                or not re.fullmatch("[0-9a-f]{32}", rows[0]["attempt_id"])
                or not isinstance(rows[0].get("status"), str)
                or rows[0].get("status") not in {"pending", "running", "retry_wait", "completed", "failed", "cancelled"}):
            raise TerminalAckUnknown("정제 성공 보고 실행권한 형식 미확인: 신규 admission 중단")
        if (rows[0]["attempt_id"] != shard["attempt_id"]
                or rows[0]["status"] in {"completed", "failed", "cancelled", "retry_wait"}):
            return False  # 닫힌/다른 token은 성공으로 인정하지 않는다.
    raise TerminalAckUnknown("정제 성공 보고 ACK 미확인·실행권한 미종결: 신규 admission 중단")


async def _report_success(client, job, shard, manifest):
    fields = {key: manifest[key] for key in ("rows_in", "rows_out", "step_counters", "schema_fingerprint",
                                             "output_id", "output_hash", "source_hash", "recipe_hash")}
    sending = asyncio.create_task(asyncio.to_thread(client.report_cleaning_shard,
        job["job_id"], shard["shard_index"], **fields,
        attempt_id=shard["attempt_id"], started_at=shard["started_at"]))
    try:
        ack = await asyncio.shield(sending)
    except asyncio.CancelledError:
        await asyncio.gather(sending, return_exceptions=True)
        raise
    except (OSError, SiloClientError, json.JSONDecodeError, UnicodeDecodeError):
        return await _reconcile_success(client, job, shard, fields)
    if _ack_matches(ack, client, job, shard, fields):
        return True
    return await _reconcile_success(client, job, shard, fields)


async def _failure(client, job_id, index, shard, message, retryable):
    try:
        await asyncio.to_thread(client.report_cleaning_shard, job_id, index,
            rows_in=0, rows_out=0, step_counters={}, error=message,
            attempt_id=shard["attempt_id"], retryable=retryable)
    except (OSError, SiloClientError):
        pass  # 연결 실패 시 중앙의 persisted deadline sweep가 정리한다.


async def _claim(client, assignment, claimed_at):
    """늦거나 잃은 claim 응답은 같은 claim_id 재전송으로 회수한다.

    서버 start는 같은 claim의 running shard를 그대로 돌려준다(새 attempt 없음). 응답을 버리면
    서버에만 running이 남아 admission이 막히고 deadline에 "정제 실행 시간초과"가 된다.
    """
    claim_id = uuid.uuid4().hex
    budget = assignment.get("timeout_seconds", 300)  # 서버 deadline 이후 재전송은 무의미하다.
    while True:
        try:
            return await asyncio.to_thread(client.start_cleaning_shard,
                assignment["job_id"], assignment["shard_index"], claim_id)
        except SiloClientError as exc:
            if exc.status in (404, 409):
                return None
            if not is_transient_error(exc) or time.monotonic() - claimed_at >= budget:
                raise
        except OSError:
            if time.monotonic() - claimed_at >= budget:
                raise
        await asyncio.sleep(1)


async def process_assignment(client: SiloClient, assignment: dict, data_dir: str,
                             executor=None) -> bool:
    """executor 인자는 이전 단발 호출 호환용이며 CPU thread 실행에는 사용하지 않는다."""
    job_id, index = assignment["job_id"], assignment["shard_index"]
    claimed_at = time.monotonic()
    job = await _claim(client, assignment, claimed_at)
    if job is None:
        return False
    shard = job["shards"][index]
    try:
        recipe = await asyncio.to_thread(client.fetch_cleaning_recipe, job["recipe_name"], job["recipe_version"])
        remaining = job["timeout_seconds"] - (time.monotonic() - claimed_at)
        if remaining <= 0:
            raise asyncio.TimeoutError()
        manifest = await _execute(client, job, shard, recipe, data_dir, remaining)
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
    # 실행 실패와 terminal 전송/ACK 실패를 구분한다. 로컬 성공 출력을 실패로 덮지 않는다.
    return await _report_success(client, job, shard, manifest)


async def _admission_ready(client, active):
    """재시작 후 소유자를 잃은 running attempt가 있으면 이 사일로의 신규 claim을 보류한다."""
    try:
        rows = await asyncio.to_thread(client.list_assigned_shards, "running")
    except (OSError, SiloClientError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("job_id"), str):
            return False
        if (row.get("status") != "running" or row.get("silo_id") != client.silo_id
                or type(row.get("shard_index")) is not int or row["shard_index"] < 0
                or type(row.get("generation")) is not int or row["generation"] < 0):
            return False
        if (row["job_id"], row["shard_index"], row["generation"]) not in active:
            return False
    return True


async def cycle(client: SiloClient, data_dir: str, executor=None, concurrency: int = 2) -> list[bool]:
    """명시적인 단발 호출만 위한 helper. 지속 worker는 아래 독립 poll loop를 사용한다."""
    if not await _admission_ready(client, {}):
        return []
    assignments = await asyncio.to_thread(client.list_assigned_shards, "pending")
    semaphore = asyncio.Semaphore(max(1, min(concurrency, 4)))
    blocked = False

    async def one(assignment):
        nonlocal blocked
        async with semaphore:
            if blocked:
                return False
            try:
                return await process_assignment(client, assignment, data_dir)
            except (TerminalAckUnknown, ExecutionCleanupError):
                blocked = True
                raise

    return await asyncio.gather(*(one(a) for a in assignments))


async def run(client: SiloClient, data_dir: str, poll_interval: float = 2,
              concurrency: int = 2, max_cycles: int = 0) -> None:
    from .distribution_runtime import DistributionCollector, run_collector
    active: dict[tuple, asyncio.Task] = {}
    limit, count = max(1, min(concurrency, 4)), 0
    # 이전 custom SDK adapter는 정제 계약만 유지. 실제 6사일로 SiloClient는 항상 수집한다.
    collector = DistributionCollector(client, data_dir) if hasattr(client, "list_distribution_configs") else None
    collection = asyncio.create_task(run_collector(collector, poll_interval)) if collector else None
    try:
        while max_cycles == 0 or count < max_cycles:
            for key, task in list(active.items()):
                if task.done():
                    del active[key]
                    try:
                        task.result()
                    except (OSError, SiloClientError) as exc:
                        # 통신 실패도 사일로 로그에 이유를 남긴다(원천·token 없음).
                        print(json.dumps({"event": "cleaning_task_error", "job_id": key[0],
                            "shard_index": key[1], "error": f"{type(exc).__name__}: {exc}"[:200]},
                            ensure_ascii=False), flush=True)
            if len(active) < limit and await _admission_ready(client, active):
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
        if collector:
            collector.stopping.set()
        for task in active.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*active.values(), return_exceptions=True)
        if collection:
            # thread 취소로 실제 I/O를 버리지 않는다. stop은 다음 호출 전 검사하고 현재 호출을 회수한다.
            await asyncio.shield(collection)


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
