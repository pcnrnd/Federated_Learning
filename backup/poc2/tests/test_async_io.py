"""비동기 I/O 헬퍼 + 대시보드 통합 + 동시성 비교 테스트"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from services import async_io


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_yaml_missing_returns_empty_dict(tmp_path):
    result = await async_io.read_yaml(tmp_path / "missing.yaml")
    assert result == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_then_read_roundtrip(tmp_path):
    path = tmp_path / "x.yaml"
    await async_io.write_yaml(path, {"k": 1, "list": [1, 2, 3]})
    got = await async_io.read_yaml(path)
    assert got == {"k": 1, "list": [1, 2, 3]}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_gather_loads_parallel(tmp_path):
    paths: list[Path] = []
    for i in range(4):
        p = tmp_path / f"f{i}.yaml"
        await async_io.write_yaml(p, {"i": i})
        paths.append(p)

    results = await async_io.gather_loads(*paths)

    assert [r["i"] for r in results] == [0, 1, 2, 3]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_gather_calls_parallel_faster_than_sequential():
    """동일한 I/O 더미 작업을 직렬 vs 병렬 실행해 wall-clock 차이 확인"""

    async def _io_sim(delay: float = 0.05) -> float:
        await asyncio.sleep(delay)
        return delay

    # 직렬
    t0 = time.perf_counter()
    for _ in range(5):
        await _io_sim(0.05)
    seq = time.perf_counter() - t0

    # 병렬
    t0 = time.perf_counter()
    await async_io.gather_calls(*[_io_sim(0.05) for _ in range(5)])
    par = time.perf_counter() - t0

    # 병렬은 직렬의 최소 절반 이하여야 한다 (이상값 마진 50%)
    assert par * 1.5 < seq


@pytest.mark.unit
@pytest.mark.asyncio
async def test_gather_calls_safe_returns_exceptions():
    async def _ok() -> int:
        return 1

    async def _fail() -> int:
        raise RuntimeError("boom")

    results = await async_io.gather_calls_safe([_ok(), _fail(), _ok()])

    assert results[0] == 1
    assert isinstance(results[1], RuntimeError)
    assert results[2] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_sync_wraps_blocking_fn():
    def _blocking_add(a: int, b: int) -> int:
        return a + b

    result = await async_io.run_sync(_blocking_add, 2, 3)

    assert result == 5
