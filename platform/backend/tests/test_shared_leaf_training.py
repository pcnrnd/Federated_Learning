"""공유 학습 함수(silo_sdk.training_runtime.train_own_leaf) — 사일로 환경(Python 3.10, 표준 라이브러리만)에서도
돌아야 한다(FL-10 로컬). flwr를 import하지 않으므로 기본 python 3.10으로 이 파일만 따로 실행할 수 있다.
"""
from __future__ import annotations

import json
import sys

import pytest

from models.federated_schemas import ParameterContribution
from services import training_round_service as rounds
from silo_sdk import training_protocol as wire
from silo_sdk import training_runtime
from silo_sdk.training_runtime import LiveWorker, train_own_leaf
from test_live_training import independent_step, request, seed


def test_shared_leaf_matches_native_worker_and_independent_gradient(tmp_path):
    ids, _roots, data, local_rows = seed(tmp_path, count=2, hierarchy=False)
    entry = rounds.create_round(request()).model_dump()

    class Local:
        def __init__(self, node):
            self.silo_id, self.api_key = node, None

        def push_live_parameters(self, envelope):
            return rounds.submit_contribution(ParameterContribution(**envelope)).model_dump()

    for node in ids:
        leaf = train_own_leaf(entry, node, str(data[node]))
        assert LiveWorker(Local(node), str(data[node])).process_round(entry)
        own = json.loads((LiveWorker.round_path(data[node] / ".training", entry["round_id"]) / "own.json").read_bytes())
        assert leaf == own  # 자체 엔진 워커가 저장한 원기여와 동일
        assert leaf["parameters"] == pytest.approx(independent_step(local_rows[node], [0.0] * 4), abs=1e-12)
        assert wire.validate_leaf(entry, leaf) is leaf
    print(json.dumps({"python": sys.version.split()[0], "silos": ids}))


def test_shared_leaf_refuses_hash_mismatch_without_training(tmp_path, monkeypatch):
    ids, _roots, data, _rows = seed(tmp_path, count=2, hierarchy=False)
    entry = rounds.create_round(request()).model_dump()
    entry["cleaning_snapshot"]["silo-1"]["output_hash"] = "0" * 64
    monkeypatch.setattr(training_runtime, "train_iterative_ridge",
                        lambda *a, **k: pytest.fail("해시가 다르면 학습하지 않아야 함"))
    with pytest.raises(ValueError, match="output_hash"):
        train_own_leaf(entry, "silo-1", str(data["silo-1"]))
    other = {**entry, "cleaning_job_id": "other"}
    entry["cleaning_snapshot"]["silo-1"] = rounds.get_round(entry["round_id"]).cleaning_snapshot["silo-1"]
    with pytest.raises(ValueError, match="사일로/작업"):
        train_own_leaf(other, "silo-1", str(data["silo-1"]))
