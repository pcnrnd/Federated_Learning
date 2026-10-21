#!/usr/bin/env python3
"""Read-only inventory of cleaned rows.json under /srv/silo-data (metadata only)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from flower_silo1.data import matrix_from_rows, resolve_feature_target


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _count_numeric(rows_path: Path, features: list[str], target: str) -> tuple[int, int, list[str]]:
    raw = rows_path.read_bytes()
    rows = json.loads(raw.decode("utf-8"))
    if not isinstance(rows, list):
        raise ValueError("rows.json must be a JSON array")
    manifest_path = rows_path.parent / "manifest.json"
    manifest = None
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _, _, seen = matrix_from_rows(rows, features, target)
    keys = sorted(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
    cols = manifest.get("columns") if manifest else keys
    return len(rows), seen, list(cols) if cols else keys


def pick_best_rows(root: Path) -> Path | None:
    """Prefer newest fed-final-* tree that has .cleaned/*/rows.json."""
    candidates: list[Path] = []
    if not root.is_dir():
        return None
    for fed_dir in sorted(root.iterdir(), reverse=True):
        if not fed_dir.is_dir() or not fed_dir.name.startswith("fed-final"):
            continue
        cleaned = fed_dir / ".cleaned"
        if not cleaned.is_dir():
            continue
        for sub in cleaned.iterdir():
            rows = sub / "rows.json"
            if rows.is_file():
                candidates.append(rows)
    if not candidates:
        # fallback: any rows.json under root (depth-limited)
        for rows in root.rglob("rows.json"):
            if ".cleaned" in rows.parts:
                candidates.append(rows)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main() -> None:
    root = Path("/srv/silo-data")
    silo_id = sys.argv[1] if len(sys.argv) > 1 else "?"
    volume = sys.argv[2] if len(sys.argv) > 2 else ""
    features = ["x1", "x2", "x3"]
    target = "y"
    rows_path = pick_best_rows(root)
    out: dict[str, object] = {
        "siloID": silo_id,
        "volume": volume,
        "data_root": str(root),
    }
    if rows_path is None:
        out["error"] = "no_cleaned_rows_found"
        print(json.dumps(out, sort_keys=True))
        sys.exit(1)
    rel = rows_path.relative_to(root).as_posix()
    raw = rows_path.read_bytes()
    row_count, numeric_usable, columns = _count_numeric(rows_path, features, target)
    out.update(
        {
            "rows_relative_path": rel,
            "rows_sha256": _sha256_bytes(raw),
            "row_count": row_count,
            "numeric_usable_rows": numeric_usable,
            "columns": columns,
        }
    )
    print(json.dumps(out, sort_keys=True))


if __name__ == "__main__":
    main()
