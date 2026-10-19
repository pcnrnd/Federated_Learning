"""G4-F3: 경로 인코딩과 충돌하지 않는 실제 ridge 모델 정체성."""
import copy

import pytest
from fastapi.testclient import TestClient

from config import settings
from g4_helpers import completed_live_result
from models.packaging_schemas import ModelRegisterRequest
from services import model_registry, ridge_artifacts
from silo_sdk import training_protocol as protocol


def renamed_result(original, name, offset):
    result = copy.deepcopy(original)
    result["model_name"] = name
    result["parameters"][-1] += offset
    result["checksum"] = protocol.parameter_checksum(result["parameters"])
    # 실제 별도 모델 공간/확정 결과 정체성을 다시 계산한다. 바깥 이름만 갈아끼우지 않는다.
    settings = {key: item for key, item in result["learning"].items() if key != "initial_parameters"}
    preprocessing = sorted({(leaf["recipe_hash"], leaf["schema_fingerprint"]) for leaf in result["origins"]})
    result["space_checksum"] = protocol.digest(dict(model_name=name, version=result["version"],
        learning=settings, preprocessing=preprocessing))
    for leaf in result["origins"]:
        leaf["space_checksum"] = result["space_checksum"]
        # contribution_id는 leaf 본문 identity(수치+기원)를 묶으므로 별도 계산한다.
        leaf["parameters"][-1] += offset
        leaf["checksum"] = protocol.parameter_checksum(leaf["parameters"])
        leaf["contribution_id"] = protocol.digest({key: value for key, value in leaf.items() if key != "contribution_id"})
    identity = dict(round_id=result["round_id"], checksum=result["checksum"],
        samples=result["total_samples"], origins=sorted(leaf["contribution_id"] for leaf in result["origins"]))
    result["result_id"] = protocol.digest(identity)
    return result


def test_json_predict_exact_names_normal_path_and_corruption_boundaries(tmp_path, monkeypatch):
    from main import app
    monkeypatch.setattr(settings, "API_KEY", None)
    original = completed_live_result(tmp_path).model_dump()
    expected = {}
    artifacts = {}
    for index, name in enumerate(("기관/a", "기관%2Fa", "기관 공백:모델", "ordinary")):
        result = renamed_result(original, name, index)
        artifact = ridge_artifacts.save_artifact(tmp_path / "artifacts", result)
        model_registry.register_model(ModelRegisterRequest(name=name, version="1.0.0", framework="ridge",
            weights_path=str(artifact.weights_path)))
        expected[name] = sum(w*x for w, x in zip(artifact.parameters[:-1], [1, 2, 3])) + artifact.parameters[-1]
        artifacts[name] = artifact
    api = TestClient(app)
    for name, value in expected.items():
        body = {"name": name, "version": "1.0.0", "inputs": [[1, 2, 3]]}
        response = api.post("/api/models/predict", json=body)
        assert response.status_code == 200
        assert response.json()["model"] == name
        assert response.json()["predictions"] == pytest.approx([value])
        assert response.json()["weights_checksum"] == artifacts[name].weights_sha256
        assert api.post("/api/models/predict", json={**body, "inputs": [[1, 2]]}).status_code == 422
        assert api.post("/api/models/predict", json={**body, "inputs": [[True, 2, 3]]}).status_code == 422
    assert expected["기관/a"] != expected["기관%2Fa"]
    old_path = api.post("/api/models/ordinary/1.0.0/predict", json={"inputs": [[1, 2, 3]]})
    assert old_path.status_code == 200 and old_path.json()["predictions"] == pytest.approx([expected["ordinary"]])
    for name, artifact in artifacts.items():
        artifact.weights_path.write_bytes(b"corrupt")
        assert api.post("/api/models/predict", json={"name": name, "version": "1.0.0", "inputs": [[1, 2, 3]]}).status_code == 409
    api.close()
