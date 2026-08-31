"""YAML 파일 기반 DictRepository 구현."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config.yaml_store import load_yaml, save_yaml_atomic


class YamlDictRepository:
    """단일 YAML mapping 파일을 감싸는 Repository."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, Any]:
        return load_yaml(self._path)

    def save(self, data: dict[str, Any]) -> None:
        save_yaml_atomic(self._path, data)
