"""YAML 파일 기반 DictRepository 구현."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config.yaml_store import load_yaml, save_yaml_atomic


class YamlDictRepository:
    """단일 YAML mapping 파일을 감싸는 Repository.

    get/upsert는 SQLite 백엔드와 인터페이스를 맞추기 위한 것으로, YAML에서는 파일 전체를
    읽고 다시 쓴다 — 이력이 커지면 쓰기당 O(n). 단일 파일 원자 교체(os.replace)라 부분
    쓰기는 남지 않는다. 처리량이 필요하면 FED_STORAGE=sqlite.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, Any]:
        return load_yaml(self._path)

    def get(self, key: str) -> Any | None:
        return self.load().get(key)

    def upsert(self, key: str, payload: Any) -> None:
        data = dict(self.load())
        data[key] = payload
        self.save(data)

    def save(self, data: dict[str, Any]) -> None:
        save_yaml_atomic(self._path, data)


class YamlContributionsRepository:
    """기여 원장 {round_id: {silo_id: payload}} — YAML 파일 하나에 중첩 저장."""

    def __init__(self, path: Path) -> None:
        self._inner = YamlDictRepository(path)

    def load(self) -> dict[str, Any]:
        return self._inner.load()

    def save(self, data: dict[str, Any]) -> None:
        self._inner.save(data)

    def load_round(self, round_id: str) -> dict[str, Any]:
        bucket = self._inner.load().get(round_id)
        return dict(bucket) if isinstance(bucket, dict) else {}

    def upsert(self, round_id: str, silo_id: str, payload: Any) -> None:
        data = dict(self._inner.load())
        bucket = dict(data.get(round_id) or {})
        bucket[silo_id] = payload
        data[round_id] = bucket
        self._inner.save(data)
