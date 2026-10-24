#!/usr/bin/env python3
"""Lightweight static checks without starting SuperLink/SuperNode."""

from __future__ import annotations

import ast
import compileall
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "flower_silo1"


def main() -> int:
    ok = compileall.compile_dir(PKG, quiet=1)
    if not ok:
        return 1
    for name in ("client_app.py", "server_app.py", "task.py", "data.py"):
        ast.parse((PKG / name).read_text(encoding="utf-8"))
    text = (PKG / "server_app.py").read_text(encoding="utf-8")
    for needle in (
        "fraction_evaluate=0.0",
        "min_train_nodes=expected",
        "verify_round2_base_equals_round1_result",
        "replies_list = list(replies)",
        "expected exactly {self.expected_clients} ",
    ):
        if needle not in text:
            print(f"missing server marker: {needle}", file=sys.stderr)
            return 1
    print("check_source: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
