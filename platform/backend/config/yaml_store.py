"""YAML load/save helpers with atomic writes."""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping. Missing or invalid files are treated as empty."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except (yaml.YAMLError, IOError) as exc:
        logger.warning("%s 로드 실패: %s", path, exc)
        return {}


def save_yaml_atomic(path: Path, data: dict[str, Any]) -> None:
    """Write YAML through a same-directory temp file, then replace atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        finally:
            raise
