"""학습 라운드와 독립적인 로컬 출력 수집 및 durable report/ACK 재전송."""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path

from .cleaning_output import encoded, load_output
from .client import SiloClientError, is_transient_error
from .distributions import REPORT_FIELDS, build_report, fingerprint, report_identity, sha, validate_config, window

logger = logging.getLogger(__name__)


def _atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.pending")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class DistributionCollector:
    """원시 값은 load_output→histogram 호출 범위에만 존재한다. 오류에는 종류만 남긴다."""

    def __init__(self, client, data_dir: str):
        self.client = client
        self.data_dir = data_dir
        self.directory = Path(data_dir) / ".distribution" / "reports"
        self.stopping = threading.Event()

    def _path(self, identity: str) -> Path:
        if not fingerprint(identity):
            raise ValueError("분포 로컬 식별자 불일치")
        return self.directory / f"{identity}.json"

    def _read(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        record = json.loads(path.read_bytes())
        if (not fingerprint(path.stem) or not isinstance(record, dict)
                or record.get("status") not in ("pending", "acked", "blocked", "retry")):
            raise ValueError("보존 분포 상태 불일치")
        if record.get("report") is not None:
            report = record["report"]
            if (not isinstance(report, dict) or set(report) != REPORT_FIELDS
                    or report.get("report_id") != path.stem or report["report_hash"]
                    != sha({k: v for k, v in report.items() if k != "report_hash"})):
                raise ValueError("보존 분포 보고서 해시 불일치")
        elif record["status"] in ("pending", "acked"):
            raise ValueError("보존 분포 payload가 없습니다")
        return record

    def _send(self, path: Path, record: dict) -> None:
        if record["status"] != "pending" or self.stopping.is_set():
            return
        report = record["report"]
        try:
            ack = self.client.push_distribution_report(report)
            if ack != {"report_id": report["report_id"], "report_hash": report["report_hash"], "accepted": True}:
                raise OSError("분포 ACK 식별자 불일치")
            _atomic(path, {"status": "acked", "report": report})
        except (OSError, SiloClientError) as exc:
            # ACK 유실/통신 실패는 같은 payload로 재전송. 영구 4xx는 조용히 새 보고서를 만들지 않는다.
            status = "pending" if is_transient_error(exc) else "blocked"
            _atomic(path, {"status": status, "report": report, "error_code": type(exc).__name__})

    def _collect(self, config: dict, job: dict, shard: dict) -> bool:
        start, end = window(shard["completed_at"], config["window_seconds"])
        identity = report_identity({"node_id": self.client.silo_id, "output_id": shard["output_id"],
            "output_hash": shard["output_hash"], "config_id": config["config_id"],
            "feature": config["feature"], "window_start": start, "window_end": end})
        path = self._path(identity)
        try:
            record = self._read(path)
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("분포 journal 읽기 보류; 원본 보존·해당 출력 전송 대기")
            return False
        if record is not None and record["status"] != "retry":
            return False  # 오래된 ACK가 batch 한도를 소비해 새 출력을 굶기지 않는다.
        try:
            rows, manifest = load_output(self.data_dir, dict(shard, generation=job["generation"]))
            if (manifest["silo_id"] != self.client.silo_id or manifest["job_id"] != job["job_id"]
                    or manifest["attempt_id"] != shard["attempt_id"]):
                raise ValueError("분포 로컬 출력 계보 불일치")
            report = build_report(rows, manifest, config, shard)
            record = {"status": "pending", "report": report}
        except OSError:
            record = {"status": "retry", "report": None, "error_code": "local_output_io"}
        except (ValueError, KeyError, TypeError):
            record = {"status": "blocked", "report": None, "error_code": "invalid_local_output"}
        _atomic(path, record)  # POST 이전에 exact payload 또는 별도 실패 상태를 보존.
        self._send(path, record)
        return True

    def cycle(self, limit: int = 16) -> None:
        """한 번에 제한된 새 출력만 읽으며 pending 재전송을 먼저 처리한다."""
        for path in sorted(self.directory.glob("*.json")):
            if self.stopping.is_set():
                return
            try:
                record = self._read(path)
            except (OSError, ValueError, KeyError, TypeError):
                logger.warning("분포 journal 읽기 보류; 원본 보존·다른 출력 수집 계속")
                continue
            if record:
                self._send(path, record)
        if self.stopping.is_set():
            return
        configs = [validate_config(c) for c in self.client.list_distribution_configs()]
        if not configs:
            return
        assignments = self.client.list_assigned_shards("completed")
        collected = 0
        for assignment in assignments:
            if self.stopping.is_set():
                return
            relevant = [c for c in configs if c["recipe_name"] == assignment["recipe_name"]
                        and c["recipe_version"] == assignment["recipe_version"]]
            if not relevant:
                continue
            job = self.client.get_cleaning_job(assignment["job_id"])
            for shard in job["shards"]:
                if shard["shard_index"] != assignment["shard_index"] or shard["silo_id"] != self.client.silo_id:
                    continue
                if shard["status"] != "completed" or not shard.get("output_id"):
                    continue  # legacy 행 수 전용 성공은 검증된 로컬 출력이 아니다.
                for config in relevant:
                    if self.stopping.is_set():
                        return
                    collected += int(self._collect(config, job, shard))
                    if collected >= limit:
                        return


async def run_collector(collector: DistributionCollector, poll_interval: float) -> None:
    import asyncio
    while not collector.stopping.is_set():
        try:
            await asyncio.to_thread(collector.cycle)
        except Exception as exc:  # noqa: BLE001
            logger.warning("분포 로컬 수집 보류: %s", type(exc).__name__)
        # 정제 claim loop와 독립적으로 동작하며 종료 신호를 짧은 간격으로 확인한다.
        for _ in range(max(1, int(max(0.1, poll_interval) * 10))):
            if collector.stopping.is_set():
                return
            await asyncio.sleep(0.1)
