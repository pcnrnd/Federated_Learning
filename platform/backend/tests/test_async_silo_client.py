"""AsyncSiloClient — 다중 push 병렬 처리 검증"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SDK_PARENT = Path(__file__).resolve().parent.parent
if str(SDK_PARENT) not in sys.path:
    sys.path.insert(0, str(SDK_PARENT))

from silo_sdk import AsyncSiloClient  # noqa: E402


def _ok_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_push_metric_invokes_endpoint():
    captured: dict = {}

    def _fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _ok_response({"ok": True})

    client = AsyncSiloClient("http://central:8000", silo_id="silo-2")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        await client.push_metric("alpha", "1.0.0", "accuracy", 0.95)

    assert captured["url"] == "http://central:8000/api/monitoring/metrics"
    assert captured["body"]["value"] == 0.95


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_push_parameters_forwards_aggregated_from():
    captured: dict = {}

    def _fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _ok_response({"round_id": "r1"})

    client = AsyncSiloClient("http://central:8000", silo_id="silo-1")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        await client.push_parameters(
            "r1", 40, [4.0, 5.0], aggregated_from=["silo-3", "silo-4"]
        )

    assert captured["body"]["aggregated_from"] == ["silo-3", "silo-4"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_client_forwards_api_key_header():
    captured: dict = {}

    def _fake_urlopen(req, timeout):
        captured["api_key"] = req.get_header("X-fed-api-key")
        return _ok_response({"ok": True})

    client = AsyncSiloClient("http://central:8000", silo_id="silo-2", api_key="secret")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        await client.push_metric("alpha", "1.0.0", "accuracy", 0.95)

    assert captured["api_key"] == "secret"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_push_many_metrics_runs_in_parallel():
    """5개 push를 직렬과 병렬로 실행 — 병렬이 분명히 빠른지 검증.

    각 요청을 50ms 지연으로 모킹 → 직렬 ≈ 250ms, 병렬 ≈ 50~100ms.
    """

    def _slow_urlopen(req, timeout):
        time.sleep(0.05)
        return _ok_response({"ok": True})

    client = AsyncSiloClient("http://central:8000", silo_id="silo-2")
    samples = [
        ("alpha", "1.0.0", "accuracy", float(i))
        for i in range(5)
    ]

    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_slow_urlopen):
        t0 = time.perf_counter()
        results = await client.push_many_metrics(samples)
        elapsed = time.perf_counter() - t0

    assert len(results) == 5
    # 직렬이라면 ≈ 250ms 이상. 병렬이면 ≈ 50~150ms.
    assert elapsed < 0.25, f"expected parallel (<250ms), got {elapsed:.3f}s"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_client_propagates_4xx_as_exception():
    import urllib.error

    err = urllib.error.HTTPError(
        url="http://central:8000/api/monitoring/metrics",
        code=404,
        msg="Not Found",
        hdrs=None,  # type: ignore[arg-type]
        fp=BytesIO(b"{}"),
    )
    client = AsyncSiloClient("http://central:8000", silo_id="silo-2")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=err):
        with pytest.raises(Exception):
            await client.push_metric("alpha", "1.0.0", "accuracy", 0.5)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_compose_with_other_coroutines():
    """SDK 호출과 비-IO 작업을 같은 gather로 묶을 수 있는지"""

    def _fake_urlopen(req, timeout):
        return _ok_response({"ok": True})

    async def _other_work() -> int:
        await asyncio.sleep(0.01)
        return 42

    client = AsyncSiloClient("http://central:8000", silo_id="silo-2")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        a, b = await asyncio.gather(
            client.push_metric("alpha", "1.0.0", "accuracy", 0.9),
            _other_work(),
        )

    assert a == {"ok": True}
    assert b == 42
