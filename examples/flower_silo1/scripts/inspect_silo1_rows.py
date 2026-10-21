#!/usr/bin/env python3
"""Print keys/count/hash only for pinned Silo1 cleaned rows (read-only)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROWS = Path(
    "/srv/silo-data/fed-final-path603396-20261021/.cleaned/"
    "f27880259e7c004a83f7515ca6ad70a792ee7cba6d4897a28994c1689f69f939/rows.json"
)


def main() -> None:
    raw = ROWS.read_bytes()
    rows = json.loads(raw)
    manifest = json.loads((ROWS.parent / "manifest.json").read_text(encoding="utf-8"))
    print("rows_sha256", hashlib.sha256(raw).hexdigest())
    print("row_count", len(rows))
    print("row_keys", sorted(rows[0].keys()) if rows else [])
    print("manifest_columns", manifest.get("columns"))
    print("manifest_rows_out", manifest.get("rows_out"))


if __name__ == "__main__":
    main()
