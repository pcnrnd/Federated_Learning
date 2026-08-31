"""비동기 I/O 헬퍼 — asyncio.to_thread 기반.

설계 목표:
  * 외부 의존성 추가 없이 (aiofiles 미사용) 기존 동기 YAML I/O를 비동기로 감싼다.
  * I/O bound 작업을 이벤트 루프 차단 없이 처리 — FastAPI 핸들러가 동시에 여러 요청을 처리 가능.
  * `gather_loads`로 N개의 YAML 로드를 단일 await로 병렬 수행.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

import yaml
from config.yaml_store import save_yaml_atomic


async def read_yaml(path: Path) -> dict[str, Any]:
    """YAML 파일을 백그라운드 스레드에서 비동기 로드"""

    def _read() -> dict[str, Any]:
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}

    return await asyncio.to_thread(_read)


async def write_yaml(path: Path, data: dict[str, Any]) -> None:
    """YAML 파일을 백그라운드 스레드에서 비동기 저장"""

    def _write() -> None:
        save_yaml_atomic(path, data)

    await asyncio.to_thread(_write)


async def gather_loads(*paths: Path) -> tuple[dict[str, Any], ...]:
    """여러 YAML 파일을 병렬로 로드. 단일 요청에서 N개 YAML이 필요할 때 사용."""
    results = await asyncio.gather(*(read_yaml(p) for p in paths))
    return tuple(results)


async def run_sync(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """동기 함수를 비동기 컨텍스트에서 호출 — 이벤트 루프 차단 방지."""
    return await asyncio.to_thread(fn, *args, **kwargs)


async def gather_calls(*coros: Awaitable[Any]) -> tuple[Any, ...]:
    """여러 코루틴을 병렬 실행 — 첫 예외 발생 시 즉시 전파"""
    return tuple(await asyncio.gather(*coros))


async def gather_calls_safe(
    coros: Iterable[Awaitable[Any]],
) -> list[Any | Exception]:
    """병렬 실행 — 예외는 결과 리스트에 그대로 담아 반환 (partial failure 허용)."""
    return list(await asyncio.gather(*coros, return_exceptions=True))
