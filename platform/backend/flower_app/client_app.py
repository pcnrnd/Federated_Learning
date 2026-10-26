"""Flower ClientApp — SuperNode(사일로) 쪽 로컬 학습.

10-21 예제(examples/flower_silo1/client_app.py)와 달리 데이터 경로를 고정하지 않는다. 받은 라운드의
정제 결과 ID·해시로 보존 출력을 찾고(silo_sdk.cleaning_output.load_output), 해시가 다르면 학습하지
않고 오류 코드만 돌려준다. 학습은 자체 엔진과 같은 silo_sdk.training_runtime.train_own_leaf.
"""
from __future__ import annotations

import json
import os

from flwr.app import ConfigRecord, Context, Message, RecordDict
from flwr.clientapp import ClientApp

from silo_sdk import training_protocol as protocol
from silo_sdk.training_runtime import train_own_leaf

app = ClientApp()


def train_reply(round_json: str, silo_id: str, data_dir: str) -> dict[str, str]:
    """라운드 JSON → 응답 필드. 원시 행·경로·예외 본문은 돌려주지 않는다."""
    entry = json.loads(round_json)
    if silo_id not in protocol.participants(entry):
        return {"silo-id": silo_id, "error": "not_participant"}
    try:
        protocol.validate_round(entry)
        leaf = train_own_leaf(entry, silo_id, data_dir)
    except FileNotFoundError:
        return {"silo-id": silo_id, "error": "input_missing"}
    except (ValueError, KeyError, TypeError):
        return {"silo-id": silo_id, "error": "invalid_model_or_input"}
    return {"silo-id": silo_id, "leaf": protocol.encoded(leaf).decode("ascii")}


@app.train()
def train(msg: Message, context: Context) -> Message:
    reply = train_reply(str(msg.content["config"]["round"]),
                        os.environ.get("SILO_ID", ""),
                        os.environ.get("SILO_DATA_ROOT", "/srv/silo-data"))
    print(json.dumps({"event": "flower_client_train", "node_id": context.node_id,
                      **{k: v for k, v in reply.items() if k != "leaf"}}), flush=True)
    return Message(RecordDict({"config": ConfigRecord(reply)}), reply_to=msg)
