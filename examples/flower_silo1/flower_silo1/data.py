"""Read-only Silo1 cleaned rows from a mounted volume."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

Row = dict[str, Any]

DEFAULT_ROWS_REL = (
    "fed-final-path603396-20261021/.cleaned/"
    "f27880259e7c004a83f7515ca6ad70a792ee7cba6d4897a28994c1689f69f939/rows.json"
)
PINNED_ROWS_SHA256 = (
    "8164fad0f8a29f18c677a99ad7e791b76e3c318dc15569d27bd2ea5432837356"
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_rows_path() -> Path:
    """Resolve ``rows.json`` from ``SILO1_ROWS_JSON`` or ``SILO1_DATA_ROOT``."""
    explicit = os.environ.get("SILO1_ROWS_JSON")
    if explicit:
        return Path(explicit)
    root = os.environ.get("SILO1_DATA_ROOT", "/srv/silo-data")
    return Path(root) / DEFAULT_ROWS_REL


def load_rows_and_manifest() -> tuple[list[Row], dict[str, Any] | None]:
    """Load cleaned rows and optional sibling ``manifest.json``."""
    rows_path = resolve_rows_path()
    if not rows_path.is_file():
        raise FileNotFoundError(f"Silo1 rows not found: {rows_path}")
    raw = rows_path.read_bytes()
    expect = os.environ.get("SILO1_ROWS_SHA256", PINNED_ROWS_SHA256)
    digest = _sha256_bytes(raw)
    if expect and digest != expect:
        raise ValueError(
            f"rows.json sha256 mismatch (got {digest}, expected {expect})"
        )
    rows = json.loads(raw.decode("utf-8"))
    if not isinstance(rows, list):
        raise ValueError("rows.json must be a JSON array")
    manifest_path = rows_path.parent / "manifest.json"
    manifest = None
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return rows, manifest


def resolve_feature_target(
    rows: list[Row],
    manifest: dict[str, Any] | None,
    *,
    run_feature_columns: list[str],
    run_target_column: str,
) -> tuple[list[str], str]:
    """Pick feature and target columns from run config, env, or manifest metadata."""
    target = (
        os.environ.get("SILO1_TARGET_COLUMN")
        or run_target_column
        or (manifest or {}).get("target_column")
        or ""
    )
    features = list(run_feature_columns)
    if os.environ.get("SILO1_FEATURE_COLUMNS"):
        features = [
            c.strip()
            for c in os.environ["SILO1_FEATURE_COLUMNS"].split(",")
            if c.strip()
        ]
    if not features and manifest and manifest.get("columns"):
        columns = list(manifest["columns"])
        if not target and len(columns) >= 2:
            target = str(columns[-1])
        features = [c for c in columns if c != target]
    if not target:
        raise ValueError(
            "Set SILO1_TARGET_COLUMN or tool.flwr.app.config target-column "
            "after inspecting manifest/rows schema"
        )
    if not features:
        raise ValueError(
            "Set SILO1_FEATURE_COLUMNS or tool.flwr.app.config feature-columns"
        )
    if not rows:
        raise ValueError("rows.json is empty")
    sample = rows[0]
    if not isinstance(sample, dict):
        raise ValueError("rows must be objects")
    for name in [*features, target]:
        if name not in sample:
            raise KeyError(f"column {name!r} missing from rows")
    return features, target


def matrix_from_rows(
    rows: list[Row], feature_columns: list[str], target_column: str
) -> tuple[list[list[float]], list[float], int]:
    """Build finite numeric training matrices; return usable rows and rows seen."""
    xs: list[list[float]] = []
    ys: list[float] = []
    seen = 0
    for row in rows:
        seen += 1
        values: list[float | None] = []
        for col in [*feature_columns, target_column]:
            raw = row.get(col)
            if raw is None or isinstance(raw, bool):
                values.append(None)
                continue
            try:
                num = float(raw)
            except (TypeError, ValueError, OverflowError):
                values.append(None)
                continue
            if num != num or num in (float("inf"), float("-inf")):
                values.append(None)
                continue
            values.append(num)
        if any(v is None for v in values):
            continue
        xs.append(values[:-1])  # type: ignore[arg-type]
        ys.append(values[-1])  # type: ignore[arg-type]
    if not xs:
        raise ValueError("no finite numeric rows for training")
    return xs, ys, seen
