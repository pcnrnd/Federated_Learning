"""고정 모델 이미지의 daemon 간 전달·실제 endpoint/예측 확인. 원시 응답은 저장/로그하지 않는다."""
from __future__ import annotations

import hashlib
import json
import math
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import docker
from docker.errors import ImageNotFound

from models.packaging_schemas import DeploymentTargetResult
from services import model_registry


def pinned_package(entry, request):
    from services.packaging_service import get_package
    record = get_package(entry.name, entry.version)
    if record.status != "built" or not record.image_digest or not record.weights_checksum:
        raise ValueError("실제 빌드·가중치 정체성이 확인된 패키지가 필요합니다")
    if request.image_tag and request.image_tag not in (record.image_tag, record.image_digest):
        raise ValueError("요청한 이미지가 등록 패키지와 다릅니다")
    if entry.framework == "ridge":
        artifact = model_registry.get_ridge_artifact(entry)
        if (artifact.weights_sha256 != record.weights_checksum or artifact.artifact_id != record.artifact_id
                or artifact.manifest_sha256 != record.manifest_checksum):
            raise ValueError("패키지와 현재 등록 artifact가 다릅니다")
    identity = dict(model=entry.name, version=entry.version, framework=entry.framework,
                    weights_checksum=record.weights_checksum)
    if entry.framework == "ridge":
        identity.update(artifact_id=record.artifact_id, manifest_checksum=record.manifest_checksum,
                        result_id=entry.metadata["result_id"])
    return record.image_digest, identity


def ensure_image(client, expected_id, identity):
    """mutable tag 대신 image ID를 전송·조회한다. load_image의 file-like 스트림으로 메모리를 제한한다."""
    try:
        image = client.images.get(expected_id)
    except ImageNotFound:
        central = docker.from_env()
        try:
            source = central.images.get(expected_id)
            if source.id != expected_id:
                raise ValueError("전송할 중앙 이미지 ID 불일치")
            with tempfile.TemporaryFile() as payload:
                stream = source.save(named=False)
                try:
                    for chunk in stream:
                        payload.write(chunk)
                finally:
                    if hasattr(stream, "close"):
                        stream.close()
                payload.seek(0)
                response = client.api.load_image(payload, quiet=True)
                try:
                    for item in response:
                        value = json.loads(item) if isinstance(item, (bytes, str)) else item
                        if value.get("error") or value.get("errorDetail"):
                            raise ValueError("대상 daemon 이미지 전송 실패")
                finally:
                    if hasattr(response, "close"):
                        response.close()
            image = client.images.get(expected_id)
        finally:
            central.close()
    if image.id != expected_id:
        raise ValueError("대상 daemon의 실제 이미지 ID가 다릅니다")
    labels = image.attrs.get("Config", {}).get("Labels", {}) or {}
    for field, label in (("weights_checksum", "fed.weights_checksum"), ("artifact_id", "fed.artifact_id"),
                         ("manifest_checksum", "fed.manifest_checksum")):
        if identity.get(field) and labels.get(label) != identity[field]:
            raise ValueError("대상 이미지와 모델/가중치 정체성 불일치")
    return image


def probe_inputs(model, request):
    if request.probe_inputs is not None:
        values = request.probe_inputs
    else:
        features = model.metadata.get("features") or model.input_schema.get("features")
        if not isinstance(features, list) or not features:
            raise ValueError("모델 입력 schema 또는 명시적인 예측 검증 입력이 필요합니다")
        values = [[0.0] * len(features)]
    json.dumps(values, allow_nan=False)
    if model.framework == "ridge":
        from services.ridge_artifacts import predict
        predict(model_registry.get_ridge_artifact(model), values)
    return values


def endpoint_for(client, container, node_info, port):
    container.reload()
    bindings = container.attrs.get("NetworkSettings", {}).get("Ports", {}).get(f"{port}/tcp") or []
    if not bindings or not bindings[0].get("HostPort"):
        raise ValueError("실제 컨테이너 포트가 할당되지 않았습니다")
    address = bindings[0].get("HostIp")
    if address in (None, "", "0.0.0.0", "::"):
        parsed = urllib.parse.urlparse(node_info.get("base_url", ""))
        address = parsed.hostname or "127.0.0.1"
    if ":" in address:
        address = f"[{address}]"
    return f"http://{address}:{int(bindings[0]['HostPort'])}"


def _json_request(url, body=None):
    payload = None if body is None else json.dumps(body, allow_nan=False).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=2) as response:
        data = response.read(1024*1024 + 1)
    if len(data) > 1024*1024:
        raise ValueError("검증 응답 크기가 한도를 초과했습니다")
    return json.loads(data)


def _finite_predictions(values):
    if isinstance(values, list) and values:
        for value in values:
            _finite_predictions(value)
    elif isinstance(values, bool) or not isinstance(values, (int, float)) or not math.isfinite(values):
        raise ValueError("실제 유한 예측 결과가 필요합니다")


def verify_target(client, container, node_info, entry, model, request, *, timeout=20):
    inputs = probe_inputs(model, request)
    deadline = time.monotonic() + timeout
    while True:
        try:
            container.reload()
            if container.image.id != entry.expected_image_id:
                raise ValueError("실제 컨테이너가 고정 이미지와 다릅니다")
            if container.status in ("created", "restarting"):
                raise OSError("컨테이너 시작 대기")
            if container.status != "running":
                raise ValueError("실제 컨테이너가 실행 중이지 않습니다")
            endpoint = endpoint_for(client, container, node_info, request.inference_port)
            health = _json_request(endpoint + "/health")
            prediction = _json_request(endpoint + "/predict", {"inputs": inputs})
            if health.get("status") != "ok" or prediction.get("ok") is not True or prediction.get("input_count") != len(inputs):
                raise ValueError("실제 health/predict 완료 응답이 아닙니다")
            for field, expected in entry.expected_identity.items():
                if health.get(field) != expected or prediction.get(field) != expected:
                    raise ValueError("실제 health/predict의 모델 정체성 불일치")
            values = prediction.get("predictions")
            if not isinstance(values, list) or len(values) != len(inputs):
                raise ValueError("실제 예측 결과의 입력/출력 건수가 다릅니다")
            _finite_predictions(values)
            if model.framework == "ridge":
                from services.ridge_artifacts import predict
                expected = predict(model_registry.get_ridge_artifact(model), inputs)
                if len(values) != len(expected) or any(not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
                        for a, b in zip(values, expected)):
                    raise ValueError("실제 ridge 예측과 고정 가중치 계산 불일치")
            checksum = hashlib.sha256(json.dumps(values, allow_nan=False, separators=(",", ":")).encode()).hexdigest()
            return DeploymentTargetResult(status="running", container_id=container.id, image_id=container.image.id,
                endpoint=endpoint, weights_checksum=health["weights_checksum"], prediction_checksum=checksum,
                verified_at=datetime.now(timezone.utc).isoformat())
        except (urllib.error.URLError, TimeoutError, OSError):
            if time.monotonic() >= deadline:
                raise TimeoutError("대상 health/predict 확인 시간 초과") from None
            time.sleep(.2)
