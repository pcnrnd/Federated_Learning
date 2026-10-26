"""실제 SuperLink·SuperNode로 Flower 실행 1회 (flower_live 마커). dts 시험 스택 안에서만 실행한다.

로컬·CI에는 SuperLink가 없어 FED_FLOWER_LIVE_REQUEST가 없으면 건너뛴다.
필요 환경:
- FED_FLOWER_SUPERLINK: SuperLink Control API 주소 (예: superlink:8000)
- FED_FLOWER_EXCHANGE_DIR: SuperLink와 같은 경로로 마운트한 교환 볼륨
- FED_FLOWER_LIVE_REQUEST: 시험 백엔드가 쓴 request.json (운영 데이터 사본의 정제 결과 ID·해시)
선택:
- FED_FLOWER_LIVE_EXPECT_STATUS: 기대 상태 (기본 finished:completed, 장애 주입 시 finished:failed)
- FED_FLOWER_LIVE_NATIVE_RESULT: 자체 엔진 결과 JSON(parameters) — FL-3 허용오차 비교
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from models.federated_schemas import TrainingRound
from services import flower_engine

pytestmark = [
    pytest.mark.flower_live,
    pytest.mark.skipif(not os.getenv("FED_FLOWER_LIVE_REQUEST"), reason="실제 SuperLink 시험 환경(dts)에서만 실행"),
]


def test_live_flower_run():
    request = json.loads(Path(os.environ["FED_FLOWER_LIVE_REQUEST"]).read_bytes())
    request["round_id"] = f"live-{uuid.uuid4().hex[:12]}"  # 시험 백엔드 라운드 결과를 덮지 않음
    entry = TrainingRound(**request, group_id="flower-live", min_contributions=1, status="open",
                          created_at=datetime.now(timezone.utc).isoformat(), engine="flower")
    run_id = flower_engine.submit(entry)
    deadline = time.monotonic() + flower_engine._timeout_seconds()
    status, details = flower_engine.run_status(run_id)
    while not status.startswith("finished") and time.monotonic() < deadline:
        time.sleep(2)
        status, details = flower_engine.run_status(run_id)
    result = flower_engine._read_result(entry.round_id) or {}
    print(json.dumps({"run_id": run_id, "status": status, "details": details,
                      "result_status": result.get("status"), "error": result.get("error"),
                      "samples": result.get("samples"), "losses": result.get("losses")}, ensure_ascii=False))
    expected = os.getenv("FED_FLOWER_LIVE_EXPECT_STATUS", "finished:completed")
    assert status == expected
    if expected != "finished:completed":
        assert result.get("status") == "failed" and result.get("error")
        return
    assert result["status"] == "completed"
    assert flower_engine._aggregate_matches(result["leaves"], result["aggregate"])
    native_path = os.getenv("FED_FLOWER_LIVE_NATIVE_RESULT")
    if native_path:
        native = json.loads(Path(native_path).read_bytes())["parameters"]
        error = max(abs(a - b) for a, b in zip(native, result["aggregate"]))
        print(json.dumps({"fl3_max_abs_error": error, "atol": flower_engine.AGGREGATE_ATOL}))
        assert len(native) == len(result["aggregate"]) and error <= flower_engine.AGGREGATE_ATOL
