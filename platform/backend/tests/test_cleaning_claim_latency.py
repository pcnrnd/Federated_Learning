"""F1: 늦은 claim 응답이 실행권한을 고아로 만들지 않고, 폴링이 원장을 재파싱하지 않는다.

DTS 10-22 실측: 6사일로 동시 claim 중 뒤 순서 /start 응답이 사일로 2초 HTTP 한도를 넘겨
서버만 running을 기록하고 사일로는 실행하지 않아 deadline에 "정제 실행 시간초과"가 됐다.
"""
from __future__ import annotations

import asyncio
import urllib.error
from datetime import timedelta

from config import cleaning_manager
from services import cleaning_execution as server, cleaning_job_service as jobs
import test_cleaning_progress_delivery as delivery
from test_cleaning_progress_delivery import Bridge, create
from silo_sdk import cleaning_runtime as worker

world = delivery.world  # 6사일로 원천·레시피·그룹 fixture 재사용


class LateClaimAck(Bridge):
    """서버는 claim을 기록했지만 응답은 클라이언트 timeout으로 잃는다(첫 호출만)."""

    def __init__(self, node="silo-1", lost=1):
        super().__init__(node)
        self.lost, self.claim_ids = lost, []

    def start_cleaning_shard(self, identity, index, claim):
        self.claim_ids.append(claim)
        job = super().start_cleaning_shard(identity, index, claim)
        if len(self.claim_ids) <= self.lost:
            raise TimeoutError("timed out")
        return job


def test_lost_claim_ack_is_resent_with_same_claim_and_runs(world):
    nodes, path = world
    create("late")
    client = LateClaimAck(nodes[0])
    assert asyncio.run(worker.process_assignment(client,
        {"job_id": "late", "shard_index": 0, "timeout_seconds": 20}, str(path / nodes[0]))) is True
    shard = jobs.get_job("late").shards[0]
    assert len(set(client.claim_ids)) == 1 and len(client.claim_ids) == 2
    assert shard.status == "completed" and shard.attempt == len(shard.attempts) == 1


def test_unreachable_claim_gives_up_within_shard_timeout(world, monkeypatch):
    nodes, path = world
    create("down")

    class Down(Bridge):
        calls = 0

        def start_cleaning_shard(self, identity, index, claim):
            Down.calls += 1
            raise urllib.error.URLError("refused")

    monkeypatch.setattr(worker.asyncio, "sleep", _instant_sleep)
    try:
        asyncio.run(worker.process_assignment(Down(nodes[0]),
            {"job_id": "down", "shard_index": 0, "timeout_seconds": 0}, str(path / nodes[0])))
    except urllib.error.URLError:
        pass
    else:
        raise AssertionError("확인 못 한 claim은 실패로 끝나야 한다")
    assert Down.calls == 1 and jobs.get_job("down").shards[0].status == "pending"


async def _instant_sleep(_seconds):
    return None


def test_all_claim_acks_lost_resend_same_claim_until_server_deadline(world, monkeypatch):
    """양수 예산에서 응답을 끝내 못 받으면: 같은 claim만 재전송, 서버 deadline이 닫으면 성공·계산 없이 종료."""
    nodes, path = world
    create("lost", max_attempts=1)
    real_now = server.now

    class AlwaysLost(LateClaimAck):
        def start_cleaning_shard(self, identity, index, claim):
            if len(self.claim_ids) == 2:  # 세 번째 재전송 시점에 서버 deadline 경과
                monkeypatch.setattr(server, "now", lambda: real_now() + timedelta(seconds=30))
            return super().start_cleaning_shard(identity, index, claim)

    client = AlwaysLost(nodes[0], lost=99)
    monkeypatch.setattr(worker.asyncio, "sleep", _instant_sleep)
    assert asyncio.run(worker.process_assignment(client,
        {"job_id": "lost", "shard_index": 0, "timeout_seconds": 20}, str(path / nodes[0]))) is False
    shard = jobs.get_job("lost").shards[0]
    assert len(client.claim_ids) == 3 and len(set(client.claim_ids)) == 1
    assert shard.status == "failed" and shard.error == "정제 실행 시간초과" and shard.attempt == 1
    assert client.reports == [] and not list((path / nodes[0]).glob(".cleaned/*/manifest.json"))
    assert asyncio.run(worker._admission_ready(Bridge(nodes[0]), {})) is True  # 닫힌 claim은 고아로 남지 않는다


def test_unchanged_ledger_is_not_reparsed(world, monkeypatch):
    create("cached")
    parses = []
    original = jobs.load_jobs
    monkeypatch.setattr(jobs, "load_jobs", lambda: parses.append(1) or original())
    jobs.list_jobs()
    jobs.list_jobs()
    jobs.get_job("cached")
    assert len(parses) <= 1
    jobs.start_shard("cached", 0, "silo-1", "c")  # 쓰기 뒤에는 새 내용을 읽는다.
    assert jobs.get_job("cached").shards[0].status == "running"
    raw = cleaning_manager.JOBS_FILE.read_text(encoding="utf-8")
    cleaning_manager.JOBS_FILE.write_text(raw.replace("status: running", "status: pending"),
                                         encoding="utf-8")  # 외부 교체도 감지한다.
    assert jobs.get_job("cached").shards[0].status == "pending"

    def broken_save(_data):
        raise OSError("disk full")
    monkeypatch.setattr(jobs, "save_jobs", broken_save)
    changed = jobs.get_job("cached").model_copy(update={"status": "failed"})
    try:
        jobs._save(changed)
    except OSError:
        pass
    assert jobs.get_job("cached").status == "pending"  # 실패한 쓰기가 캐시를 오염시키지 않는다.
