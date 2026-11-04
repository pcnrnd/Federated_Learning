"""External result exchange stays independent from training and model execution."""

import json
from pathlib import Path
import subprocess
import sys
import zipfile

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from models.external_result_schemas import ExternalResultImport
from services import external_results, model_registry
from services.external_result_format import file_hash, read_bundle


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    root = inbox / "example"
    root.mkdir(parents=True)
    monkeypatch.setenv("FED_EXTERNAL_RESULTS_DIR", str(inbox))
    np.savez(root / "weights.npz", weight=np.array([1.0, 2.0], dtype=np.float32))
    # Import validates bytes, not executable code; prediction verification is separate.
    (root / "model.ts").write_bytes(b"opaque-owned-inference-fixture")
    data = {
        "format": "federated-result-v1",
        "origin": {"engine": "independent-engine"},
        "result": {
            "config": {"strategy": "fedadam"},
            "history": [{"round": 0, "accuracy": 0.1}, {"round": 1, "accuracy": 0.8}],
        },
        "metric_specs": {
            "accuracy": {"unit": "ratio", "higher_is_better": True, "range": [0, 1]}
        },
        "model": {
            "framework": "pytorch",
            "inference_format": "torchscript",
            "input_schema": {"shape": [None, 2]},
            "output_schema": {"shape": [None, 1]},
            "tensors": {"weight": {"shape": [2], "dtype": "<f4"}},
        },
        "artifacts": {
            name: {"path": filename, "sha256": file_hash(root / filename)}
            for name, filename in [
                ("weights", "weights.npz"),
                ("inference", "model.ts"),
            ]
        },
    }
    (root / "result.json").write_text(json.dumps(data), encoding="utf-8")
    return root, data


@pytest.fixture
def client():
    from api.external_results import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def request(**kw):
    return ExternalResultImport(
        bundle_id="example", name="external-model", version="1.0.0", **kw
    )


def test_import_preserves_result_and_registers_without_aggregation(
    bundle, client, monkeypatch
):
    root, original = bundle
    from services import fedavg_aggregator

    monkeypatch.setattr(
        fedavg_aggregator,
        "aggregate",
        lambda *a, **k: pytest.fail("Must not aggregate external results"),
    )
    inspected = client.post(
        "/api/external-results/inspect", json={"bundle_id": "example"}
    )
    assert inspected.status_code == 200
    assert inspected.json()["manifest"] == original
    assert inspected.json()["inference_verified"] is False
    response = client.post("/api/external-results/import", json=request().model_dump())
    assert response.status_code == 201, response.text
    entry = model_registry.get_model("external-model", "1.0.0")
    assert entry.framework == "pytorch"
    assert Path(entry.weights_path).read_bytes() == (root / "model.ts").read_bytes()
    assert entry.metadata["external_result"]["inference_verified"] is False
    assert (
        client.get(
            "/api/external-results",
            params={"name": entry.name, "version": entry.version},
        ).json()
        == original
    )
    assert (
        client.post(
            "/api/external-results/import", json=request().model_dump()
        ).status_code
        == 200
    )
    assert len(model_registry.list_models()) == 1
    (root / "model.ts").write_bytes(b"source changed")
    assert external_results.get_result(entry.name, entry.version) == original
    assert (
        client.post(
            "/api/external-results/import", json=request().model_dump()
        ).status_code
        == 422
    )


def test_version_conflict_and_stored_corruption(bundle, client):
    root, data = bundle
    assert (
        client.post(
            "/api/external-results/import", json=request().model_dump()
        ).status_code
        == 201
    )
    entry = model_registry.get_model("external-model", "1.0.0")
    data["result"]["history"][1]["accuracy"] = 0.9
    (root / "result.json").write_text(json.dumps(data), encoding="utf-8")
    assert (
        client.post(
            "/api/external-results/import", json=request().model_dump()
        ).status_code
        == 409
    )
    Path(entry.weights_path).write_bytes(b"stored model damaged")
    assert (
        client.get(
            "/api/external-results",
            params={"name": entry.name, "version": entry.version},
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "kind",
    [
        "version",
        "origin",
        "history",
        "round",
        "metric",
        "nan",
        "overflow",
        "unit",
        "profile",
        "path",
        "hash",
        "shape",
        "dtype",
        "missing",
    ],
)
def test_malformed_bundles_fail_closed(bundle, kind):
    root, data = bundle
    if kind == "version":
        data["format"] = "federated-result-v2"
    elif kind == "origin":
        data["origin"] = None
    elif kind == "history":
        data["result"]["history"] = []
    elif kind == "round":
        data["result"]["history"][1]["round"] = 0
    elif kind == "metric":
        data["result"]["history"][0]["accuracy"] = 80
    elif kind == "nan":
        data["result"]["history"][0]["accuracy"] = float("nan")
    elif kind == "overflow":
        data["result"]["history"][0]["accuracy"] = float("inf")
    elif kind == "unit":
        data["metric_specs"]["accuracy"]["unit"] = ""
    elif kind == "profile":
        data["model"]["inference_format"] = "pickle"
    elif kind == "path":
        data["artifacts"]["weights"]["path"] = "../outside.npz"
    elif kind == "hash":
        data["artifacts"]["inference"]["sha256"] = "0" * 64
    elif kind == "shape":
        data["model"]["tensors"]["weight"]["shape"] = [1000000000]
    elif kind == "dtype":
        data["model"]["tensors"]["weight"]["dtype"] = "<f8"
    else:
        del data["artifacts"]["weights"]
    (root / "result.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        read_bundle(root)
    assert model_registry.list_models() == []


@pytest.mark.parametrize(
    "kind", ["nan", "object", "duplicate", "corrupt", "empty_schema", "oversized"]
)
def test_numeric_archive_validation(bundle, kind, monkeypatch):
    root, data = bundle
    path = root / "weights.npz"
    if kind == "nan":
        np.savez(path, weight=np.array([float("nan"), 2.0], dtype=np.float32))
    elif kind == "object":
        np.savez(path, weight=np.array([object(), object()], dtype=object))
        data["model"]["tensors"]["weight"]["dtype"] = "|O"
    elif kind == "duplicate":
        with zipfile.ZipFile(path, "a") as archive:
            with pytest.warns(UserWarning):
                archive.writestr("weight.npy", archive.read("weight.npy"))
    elif kind == "corrupt":
        path.write_bytes(b"not a numeric zip")
    elif kind == "empty_schema":
        data["model"]["tensors"] = {}
    else:
        from services import external_result_format

        monkeypatch.setattr(external_result_format, "MAX_ARRAY_BYTES", 1)
    data["artifacts"]["weights"]["sha256"] = file_hash(path)
    (root / "result.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        read_bundle(root)


def test_schema_and_missing_inbox(client):
    for bundle_id in ["../other", "/absolute", "C:\\outside", ""]:
        assert (
            client.post(
                "/api/external-results/import",
                json={"bundle_id": bundle_id, "name": "x", "version": "1.0.0"},
            ).status_code
            == 422
        )
    assert (
        client.post(
            "/api/external-results/import",
            json={"bundle_id": "absent", "name": "x", "version": "wrong"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/external-results/inspect", json={"bundle_id": "absent"}
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/external-results", params={"name": "missing", "version": "1.0.0"}
        ).status_code
        == 404
    )


def test_importer_does_not_import_training_frameworks():
    backend = Path(__file__).resolve().parents[1]
    script = "import sys;from services.external_result_format import read_bundle;assert not any(k in sys.modules for k in ('defai','torch','flwr'))"
    subprocess.run([sys.executable, "-c", script], cwd=backend, check=True, timeout=30)


def test_inbox_symlink_cannot_escape(bundle, tmp_path):
    root, _ = bundle
    link = root.parent / "redirect"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks unavailable on this host")
    with pytest.raises(HTTPException) as error:
        external_results.inspect_result("redirect")
    assert error.value.status_code == 422


def test_routes_use_existing_api_key_gate(bundle, monkeypatch):
    import config.settings as settings
    from main import app

    monkeypatch.setattr(settings, "API_KEY", "test-external-key")
    client = TestClient(app)
    url = "/api/external-results/inspect"
    assert client.post(url, json={"bundle_id": "example"}).status_code == 401
    assert (
        client.post(
            url,
            json={"bundle_id": "example"},
            headers={"X-FED-API-Key": "test-external-key"},
        ).status_code
        == 200
    )


def test_legacy_model_has_no_external_result(bundle, client):
    from models.packaging_schemas import ModelRegisterRequest

    root, _ = bundle
    model_registry.register_model(
        ModelRegisterRequest(
            name="legacy",
            version="1.0.0",
            framework="pytorch",
            weights_path=str(root / "model.ts"),
            metadata={"external_result": "old-user-value"},
        )
    )
    assert (
        client.get(
            "/api/external-results", params={"name": "legacy", "version": "1.0.0"}
        ).status_code
        == 404
    )


def test_manifest_limit_and_failure_to_store(bundle, monkeypatch):
    from services import external_result_format

    root, _ = bundle
    with monkeypatch.context() as scoped:
        scoped.setattr(external_result_format, "MAX_MANIFEST_BYTES", 10)
        with pytest.raises(ValueError):
            read_bundle(root)
    monkeypatch.setattr(
        external_results,
        "_snapshot",
        lambda *args: (_ for _ in ()).throw(OSError("disk")),
    )
    with pytest.raises(HTTPException) as error:
        external_results.import_result(request())
    assert error.value.status_code == 500
    assert model_registry.list_models() == []
