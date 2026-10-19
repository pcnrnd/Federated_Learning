"""G4 파일 정체성/원자 게시와 독립 선형 예측. 운영 데이터나 Docker는 사용하지 않는다."""
from __future__ import annotations

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from services import ridge_artifacts as artifacts
from silo_sdk import training_protocol as wire


@pytest.fixture
def completed_result():
    learning = dict(solver="ridge_gradient_v1", features=["x1", "x2", "x3"], target="y",
                    initial_parameters=[0.0] * 4, l2=0.001, step_size=0.0001, steps=1)
    base = wire.parameter_checksum([0.0] * 4)
    parameters = [2.0, -3.0, 4.0, 5.0]
    outputs = {node: dict(recipe_hash="a" * 64, schema_fingerprint="b" * 64) for node in ("silo-1", "silo-2")}
    space = wire.space_checksum("model", "1.0.0", learning, outputs)
    leaves = []
    for index, count in enumerate((2, 3)):
        leaf = dict(round_id="round-1", silo_id=f"silo-{index+1}", base_checksum=base, space_checksum=space,
                    sample_count=count, rows_seen=count+1, rows_excluded=1, parameters=parameters.copy(),
                    checksum=wire.parameter_checksum(parameters), initial_objective=10.0, objective=1.0,
                    output_id=str(index+1) * 64, output_hash="c" * 64, source_hash="d" * 64,
                    recipe_hash="a" * 64, schema_fingerprint="b" * 64, attempt_id=None, generation=0)
        leaf["contribution_id"] = wire.digest(leaf)
        leaves.append(leaf)
    result = dict(round_id="round-1", parameter_dim=4, parameters=parameters, total_samples=5,
                  contributor_count=2, aggregated_at="2026-10-19T00:00:00Z", checksum=wire.parameter_checksum(parameters),
                  format="ridge-v1", model_name="model", version="1.0.0", features=learning["features"].copy(),
                  target="y", learning=learning, base_checksum=base, space_checksum=space, origins=leaves)
    result["result_id"] = wire.digest(dict(round_id=result["round_id"], checksum=result["checksum"],
        samples=5, origins=sorted(leaf["contribution_id"] for leaf in leaves)))
    return result


def test_roundtrip_preserves_actual_weights_and_g3_identity(tmp_path, completed_result):
    stored = artifacts.save_artifact(tmp_path, completed_result, version="1.0.1")
    reloaded = artifacts.load_artifact(tmp_path, stored.artifact_id,
                                      expected_manifest_sha256=stored.manifest_sha256)
    assert reloaded.parameters == (2.0, -3.0, 4.0, 5.0)
    assert reloaded.features == ("x1", "x2", "x3")
    assert reloaded.manifest["version"] == "1.0.1"
    assert reloaded.manifest["source_result"]["version"] == "1.0.0"
    assert reloaded.manifest["source_result"]["result_id"] == completed_result["result_id"]
    assert hashlib.sha256(reloaded.weights_path.read_bytes()).hexdigest() == reloaded.weights_sha256
    assert wire.parameter_checksum(list(reloaded.parameters)) == completed_result["checksum"]
    snapshot = reloaded.manifest
    snapshot["source_result"]["parameters"][0] = 999
    assert reloaded.manifest["source_result"]["parameters"][0] == 2.0
    assert not list(tmp_path.glob(".ridge-stage-*"))


def test_real_prediction_uses_ordered_features_weights_and_bias(tmp_path, completed_result):
    model = artifacts.save_artifact(tmp_path, completed_result)
    # 독립 손계산: 2*1-3*2+4*3+5=13, 2*(-1)-3*0+4*2+5=11.
    assert artifacts.predict(model, [[1, 2, 3], [-1, 0, 2]]) == [13.0, 11.0]
    assert artifacts.predict(model, [{"x3": 3, "x1": 1, "x2": 2}]) == [13.0]
    assert artifacts.predict(model, [[0, 0, 0]]) == [5.0]


def test_duplicate_completion_is_immutable_and_ignores_origin_order_and_delivery_time(tmp_path, completed_result):
    first = artifacts.save_artifact(tmp_path, completed_result)
    files = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in first.directory.iterdir()}
    duplicate = copy.deepcopy(completed_result)
    duplicate["origins"].reverse()
    duplicate["aggregated_at"] = "later-delivery"
    again = artifacts.save_artifact(tmp_path, duplicate)
    assert again.artifact_id == first.artifact_id
    assert {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in again.directory.iterdir()} == files


def test_concurrent_same_completion_publishes_one_artifact(tmp_path, completed_result):
    with ThreadPoolExecutor(max_workers=4) as executor:
        values = list(executor.map(lambda _: artifacts.save_artifact(tmp_path, completed_result), range(8)))
    assert len({value.artifact_id for value in values}) == 1
    assert [path.name for path in tmp_path.iterdir()] == [values[0].artifact_id]


@pytest.mark.parametrize("filename", ["weights.json", "manifest.json"])
def test_missing_or_corrupt_files_are_not_silently_repaired(tmp_path, completed_result, filename):
    model = artifacts.save_artifact(tmp_path, completed_result)
    path = model.directory / filename
    path.unlink()
    with pytest.raises(FileNotFoundError):
        artifacts.load_artifact(tmp_path, model.artifact_id)
    with pytest.raises(FileNotFoundError):
        artifacts.save_artifact(tmp_path, completed_result)
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        artifacts.load_artifact(tmp_path, model.artifact_id)
    assert path.read_bytes() == b"corrupt"


def test_expected_manifest_checksum_is_required_to_match_registry_reference(tmp_path, completed_result):
    model = artifacts.save_artifact(tmp_path, completed_result)
    with pytest.raises(ValueError, match="manifest checksum"):
        artifacts.load_artifact(tmp_path, model.artifact_id, expected_manifest_sha256="0" * 64)


def test_empty_weights_never_become_placeholder_success(tmp_path, completed_result):
    model = artifacts.save_artifact(tmp_path, completed_result)
    model.weights_path.write_bytes(b"")
    with pytest.raises(ValueError, match="weights"):
        artifacts.load_artifact(tmp_path, model.artifact_id)


def test_failed_manifest_write_publishes_nothing_then_retry_recovers(tmp_path, completed_result, monkeypatch):
    original = artifacts._write
    def fail_manifest(path, content):
        if path.name == "manifest.json":
            raise OSError("injected before manifest write")
        original(path, content)
    monkeypatch.setattr(artifacts, "_write", fail_manifest)
    with pytest.raises(OSError, match="injected"):
        artifacts.save_artifact(tmp_path, completed_result)
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(artifacts, "_write", original)
    recovered = artifacts.save_artifact(tmp_path, completed_result)
    assert artifacts.predict(recovered, [[0, 0, 0]]) == [5.0]


def test_failed_rename_does_not_publish_partial_artifact(tmp_path, completed_result, monkeypatch):
    original = artifacts.os.rename
    def fail_rename(_source, _destination):
        raise OSError("injected before publication")
    monkeypatch.setattr(artifacts.os, "rename", fail_rename)
    with pytest.raises(OSError, match="injected"):
        artifacts.save_artifact(tmp_path, completed_result)
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(artifacts.os, "rename", original)
    assert artifacts.save_artifact(tmp_path, completed_result).weights_path.is_file()


def test_abandoned_staging_is_not_loaded_or_overwritten(tmp_path, completed_result):
    abandoned = tmp_path / ".ridge-stage-abandoned"
    abandoned.mkdir()
    (abandoned / "weights.json").write_bytes(b"partial")
    model = artifacts.save_artifact(tmp_path, completed_result)
    assert (abandoned / "weights.json").read_bytes() == b"partial"
    assert model.directory != abandoned


@pytest.mark.parametrize("change", [
    lambda r: r.update(format="parameters-v1"),
    lambda r: r.update(parameters=[True, -3.0, 4.0, 5.0]),
    lambda r: r.update(parameters=[float("nan"), -3.0, 4.0, 5.0]),
    lambda r: r.update(parameters=[float("inf"), -3.0, 4.0, 5.0]),
    lambda r: r.update(parameter_dim=3),
    lambda r: r.update(checksum="0"*64),
    lambda r: r.update(result_id="0"*64),
    lambda r: r.update(features=["x1", "x1", "x3"]),
    lambda r: r.update(target="x1"),
    lambda r: r.update(origins=[]),
    lambda r: r.update(total_samples=6),
    lambda r: r.update(rows=[{"private": "never save"}]),
    lambda r: r["origins"][0].update(source_hash="0"*64),
    lambda r: r["origins"][0].update(rows=[{"private": "never save"}]),
    lambda r: r["learning"].update(step_size=0),
    lambda r: r["learning"].update(features=["x2", "x1", "x3"]),
])
def test_invalid_or_unbound_results_fail_before_any_file_write(tmp_path, completed_result, change):
    change(completed_result)
    with pytest.raises(ValueError):
        artifacts.save_artifact(tmp_path, completed_result)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("inputs", [
    [], [1, 2, 3], [[1, 2]], [[1, 2, 3, 4]], [[True, 2, 3]], [["1", 2, 3]],
    [[float("nan"), 2, 3]], [[1, float("inf"), 3]], [[None, 2, 3]],
    [{"x1": 1, "x2": 2}], [{"x1": 1, "x2": 2, "x3": 3, "y": 4}],
])
def test_prediction_rejects_invalid_or_mismatched_inputs(tmp_path, completed_result, inputs):
    model = artifacts.save_artifact(tmp_path, completed_result)
    with pytest.raises(ValueError):
        artifacts.predict(model, inputs)


def test_prediction_overflow_fails_with_no_raw_value_in_error(tmp_path, completed_result):
    model = artifacts.save_artifact(tmp_path, completed_result)
    with pytest.raises(ValueError) as failure:
        artifacts.predict(model, [[1e308, -1e308, 1e308]])
    assert "1e+308" not in str(failure.value)


@pytest.mark.parametrize("identity", ["../outside", "a/../b", "x"*64, "A"*64, ""])
def test_artifact_lookup_rejects_path_escape(tmp_path, identity):
    with pytest.raises(ValueError):
        artifacts.load_artifact(tmp_path, identity)


def test_duplicate_json_fields_are_rejected(tmp_path, completed_result):
    model = artifacts.save_artifact(tmp_path, completed_result)
    path = model.directory / "manifest.json"
    text = path.read_text()
    path.write_text('{"artifact_id":"'+model.artifact_id+'",'+text[1:])
    with pytest.raises(ValueError, match="중복 JSON"):
        artifacts.load_artifact(tmp_path, model.artifact_id)
