"""단일 attempt 로컬 정제 본체. 부모와는 진행/결과 metadata만 pipe로 교환한다."""
from __future__ import annotations

import json
import sys

from .cleaning_output import execute
from .client import is_transient_error
from .integration import CleaningError


def send(message):
    print(json.dumps(message), flush=True)


def main() -> int:
    request = json.load(sys.stdin)
    try:
        def progress(done, total, stage):
            send({"type": "progress", "done": done, "total": total, "stage": stage})
        manifest = execute(request["data_dir"], request["silo_id"], request["job"],
                           request["shard"], request["recipe"], progress)
        send({"type": "result", "manifest": manifest})
        return 0
    except Exception as exc:  # noqa: BLE001
        message = str(exc)[:500] if isinstance(exc, CleaningError) else f"로컬 정제 실행 실패: {type(exc).__name__}"
        send({"type": "error", "message": message, "retryable": is_transient_error(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
