"""Flower 앱 — FAB에 공유 학습 수식이 실리는지(FL-10), ServerApp·ClientApp 진입점 동작."""
from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace

import pytest

pytest.importorskip("flwr")

from flwr.cli.build import build_fab_from_disk  # noqa: E402
from flwr.cli.config_utils import load_and_validate  # noqa: E402

from flower_app import client_app, server_app  # noqa: E402
from services import flower_engine  # noqa: E402
from services import training_round_service as rounds  # noqa: E402
from test_live_training import request, seed  # noqa: E402


def test_fab_carries_shared_training_code_and_valid_config(tmp_path):
    stage = tmp_path / "app"
    flower_engine._stage_app(stage)
    config, warnings = load_and_validate(stage / "pyproject.toml", check_module=False)
    assert config["tool"]["flwr"]["app"]["components"]["clientapp"] == "flower_app.client_app:app"
    assert warnings == []
    names = set(zipfile.ZipFile(io.BytesIO(build_fab_from_disk(stage))).namelist())
    # SuperNode 이미지에는 flwr·numpy만 있다 → 공유 학습 수식이 FAB 안에 있어야 import된다
    assert {"flower_app/client_app.py", "flower_app/server_app.py", "silo_sdk/iterative_ridge.py",
            "silo_sdk/training_runtime.py", "silo_sdk/training_protocol.py",
            "silo_sdk/cleaning_output.py"} <= names
    assert not any("__pycache__" in name for name in names)


def test_flower_app_does_not_reimplement_training_math():
    from pathlib import Path
    source = "".join(Path(module.__file__).read_text(encoding="utf-8") for module in (client_app, server_app))
    assert "train_own_leaf" in source and "gradient" not in source and "step_size" not in source


def _entry(tmp_path):
    ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    entry = rounds.create_round(request()).model_dump(mode="json")
    return ids, data, entry


def _fake_message(content=None, *, reply_to=None, dst_node_id=None, message_type=None):
    # 실제 Message는 Flower 실행 문맥(run_id)이 있어야 만들어진다 — 진입점 배선만 확인
    return SimpleNamespace(content=content, reply_to=reply_to,
                           metadata=SimpleNamespace(dst_node_id=dst_node_id, message_type=message_type))


@pytest.fixture(autouse=True)
def _message_outside_run(monkeypatch):
    monkeypatch.setattr(client_app, "Message", _fake_message)
    monkeypatch.setattr(server_app, "Message", _fake_message)


def test_client_train_replies_leaf_or_error_code(tmp_path, monkeypatch):
    ids, data, entry = _entry(tmp_path)
    body = json.dumps(entry)
    message = _fake_message({"config": {"round": body}})
    monkeypatch.setenv("SILO_ID", "silo-1")
    monkeypatch.setenv("SILO_DATA_ROOT", str(data["silo-1"]))
    reply = client_app.train(message, SimpleNamespace(node_id=1))
    config = reply.content["config"]
    assert reply.reply_to is message
    leaf = json.loads(config["leaf"])
    assert config["silo-id"] == "silo-1" and leaf["silo_id"] == "silo-1" and "error" not in config
    assert client_app.train_reply(body, "silo-9", str(data["silo-1"]))["error"] == "not_participant"
    assert client_app.train_reply(body, "silo-2", str(tmp_path / "empty"))["error"] == "input_missing"
    broken = {**entry, "base_checksum": "0" * 64}
    assert client_app.train_reply(json.dumps(broken), "silo-2", str(data["silo-2"]))["error"] == "invalid_model_or_input"


class FakeGrid:
    def __init__(self, nodes, answer):
        self.nodes, self.answer, self.sent = nodes, answer, []

    def get_node_ids(self):
        return self.nodes

    def send_and_receive(self, messages, *, timeout=None):
        self.sent = list(messages)
        return [self.answer(message) for message in self.sent]


def _reply(config, node=1, error=None):
    return SimpleNamespace(has_error=lambda: error is not None, error=error, content={"config": config},
                           metadata=SimpleNamespace(src_node_id=node))


def test_server_main_writes_completed_result(tmp_path):
    ids, data, entry = _entry(tmp_path)
    round_dir = tmp_path / "exchange"
    round_dir.mkdir()
    (round_dir / "request.json").write_text(json.dumps(entry), encoding="utf-8")
    nodes = iter(ids)

    def answer(message):
        silo = next(nodes)
        return _reply(client_app.train_reply(message.content["config"]["round"], silo, str(data[silo])))

    grid = FakeGrid([11, 12], answer)
    context = SimpleNamespace(run_config={"round-dir": str(round_dir), "node-wait-seconds": 0,
                                          "reply-timeout-seconds": 5})
    server_app.main(grid, context)
    result = json.loads((round_dir / "result.json").read_bytes())
    assert result["status"] == "completed" and set(result["samples"]) == set(ids)
    assert [message.metadata.dst_node_id for message in grid.sent] == [11, 12]
    assert {message.metadata.message_type for message in grid.sent} == {"train"}


def test_server_main_fails_when_supernodes_missing_or_error(tmp_path):
    ids, data, entry = _entry(tmp_path)
    round_dir = tmp_path / "exchange"
    round_dir.mkdir()
    (round_dir / "request.json").write_text(json.dumps(entry), encoding="utf-8")
    context = SimpleNamespace(run_config={"round-dir": str(round_dir), "node-wait-seconds": 0,
                                          "reply-timeout-seconds": 5})
    with pytest.raises(RuntimeError, match="SuperNode 연결 1/2"):
        server_app.main(FakeGrid([11], lambda m: None), context)
    replies = iter([_reply({}, node=11, error=SimpleNamespace(code=1)),
                    _reply({"silo-id": "silo-2", "leaf": "{bad"}, node=12)])
    with pytest.raises(RuntimeError) as failed:
        server_app.main(FakeGrid([11, 12], lambda m: next(replies)), context)
    result = json.loads((round_dir / "result.json").read_bytes())
    assert result["errors"] == {"node-11": "client_error:1", "silo-1": "no_reply", "silo-2": "invalid_reply"}
    assert "silo-2=invalid_reply" in str(failed.value)


def test_summarize_rejects_duplicate_and_forged_leaves(tmp_path):
    ids, data, entry = _entry(tmp_path)
    good = {silo: json.loads(client_app.train_reply(json.dumps(entry), silo, str(data[silo]))["leaf"])
            for silo in ids}
    forged = {**good["silo-2"], "sample_count": good["silo-2"]["sample_count"] + 1}
    result = server_app.summarize(entry, [("silo-1", good["silo-1"], None), ("silo-1", good["silo-1"], None),
                                          ("silo-2", forged, None), ("silo-9", None, "not_participant")])
    assert result["errors"] == {"silo-1": "duplicate_reply", "silo-2": "invalid_leaf"}
