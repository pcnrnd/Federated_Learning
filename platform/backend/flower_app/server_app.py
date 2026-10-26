"""Flower ServerApp — 플랫폼 라운드 1개를 SuperNode들에 학습시키고 결과 파일을 쓴다.

10-21 예제(examples/flower_silo1/server_app.py)를 플랫폼 계약으로 옮김:
- Flower 실행 1회 = 플랫폼 라운드 1개(서버 라운드 1회). 시작 가중치·설정은 백엔드가 쓴 request.json.
- 참여 스냅샷의 사일로마다 정확히 원기여 1건이 와야 한다(예제의 N-클라이언트 게이트와 같음).
- 집계는 자체 엔진과 같은 표본 가중 평균(silo_sdk.training_protocol.weighted).
- 결과(사일로별 표본 수·손실·원기여, 집계 가중치)는 result.json에 원자적으로 쓰고, 실패면 원인을 쓴 뒤
  예외로 끝내 Flower 상태도 finished:failed가 되게 한다.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from pathlib import Path

from flwr.app import ConfigRecord, Context, Message, MessageType, RecordDict
from flwr.serverapp import Grid, ServerApp

from silo_sdk import training_protocol as protocol

app = ServerApp()


def write_result(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".pending")
    temporary.write_bytes(protocol.encoded(payload))
    os.replace(temporary, path)  # 백엔드는 완성된 결과만 본다


def parse_reply(msg: Message) -> tuple[str | None, dict | None, str | None]:
    """응답 → (silo_id, 원기여, 오류 코드)."""
    if msg.has_error():
        return f"node-{msg.metadata.src_node_id}", None, f"client_error:{msg.error.code}"
    config = msg.content["config"]
    silo_id = str(config.get("silo-id") or "") or None
    if config.get("error"):
        return silo_id, None, str(config["error"])
    try:
        return silo_id, json.loads(str(config["leaf"])), None
    except (KeyError, ValueError):
        return silo_id, None, "invalid_reply"


def summarize(entry: dict, replies: Iterable[tuple[str | None, dict | None, str | None]],
              *, connected: int | None = None) -> dict:
    """응답 묶음을 결과 파일 본문으로. 참여자 전원의 유효 원기여가 있어야 completed."""
    participants = protocol.participants(entry)
    leaves: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for silo_id, leaf, error in replies:
        if silo_id not in participants:
            if error and error != "not_participant":
                errors[silo_id or "unknown"] = error  # 사일로를 알 수 없는 SuperNode 오류도 원인에 남김
            continue
        if error:
            errors[silo_id] = error
        elif silo_id in leaves:
            errors[silo_id] = "duplicate_reply"
        else:
            try:
                leaves[silo_id] = protocol.validate_leaf(entry, leaf)
            except (ValueError, KeyError, TypeError):
                errors[silo_id] = "invalid_leaf"
    for silo_id in participants - leaves.keys() - errors.keys():
        errors[silo_id] = "no_reply"
    base = {"round_id": entry["round_id"]}
    if errors:
        reason = ", ".join(f"{silo}={code}" for silo, code in sorted(errors.items()))
        if connected is not None and connected < len(participants):
            reason = f"SuperNode 연결 {connected}/{len(participants)}; {reason}"
        return {**base, "status": "failed", "error": reason, "errors": errors}
    ordered = [leaves[silo] for silo in sorted(leaves)]
    total, aggregate = protocol.weighted(ordered)
    return {**base, "status": "completed", "leaves": ordered, "total_samples": total,
            "aggregate": aggregate, "samples": {leaf["silo_id"]: leaf["sample_count"] for leaf in ordered},
            "losses": {leaf["silo_id"]: leaf["objective"] for leaf in ordered}}


def wait_nodes(grid: Grid, expected: int, wait_seconds: float) -> list[int]:
    deadline = time.monotonic() + wait_seconds
    while True:
        nodes = list(grid.get_node_ids())
        if len(nodes) >= expected or time.monotonic() >= deadline:
            return nodes
        time.sleep(1.0)


@app.main()
def main(grid: Grid, context: Context) -> None:
    round_dir = Path(str(context.run_config["round-dir"]))
    entry = json.loads((round_dir / "request.json").read_bytes())
    result_path = round_dir / "result.json"
    expected = len(protocol.participants(entry))
    nodes = wait_nodes(grid, expected, float(context.run_config["node-wait-seconds"]))
    replies: list[Message] = []
    if len(nodes) >= expected:
        body = ConfigRecord({"round": protocol.encoded(entry).decode("ascii")})
        messages = [Message(RecordDict({"config": body}), dst_node_id=node,
                            message_type=MessageType.TRAIN) for node in nodes]
        replies = list(grid.send_and_receive(
            messages, timeout=float(context.run_config["reply-timeout-seconds"])))
    result = summarize(entry, (parse_reply(msg) for msg in replies), connected=len(nodes))
    write_result(result_path, result)
    print(json.dumps({"event": "flower_server_result", "round_id": entry["round_id"],
                      "status": result["status"], "error": result.get("error")}), flush=True)
    if result["status"] != "completed":
        raise RuntimeError(result["error"])
