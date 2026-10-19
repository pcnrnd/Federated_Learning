"""검증된 G3 ridge 결과의 불변 파일 저장과 실제 선형 추론.

stdlib만 사용하므로 같은 코드를 추론 이미지에 포함할 수 있다.
등록/버전 선택/패키지 빌드는 호출 서비스가 맡는다. 원시 행은 저장하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

_lock = RLock()
_RESULT_FIELDS = {"round_id", "parameter_dim", "parameters", "total_samples", "contributor_count",
    "aggregated_at", "result_id", "checksum", "format", "model_name", "version", "features", "target",
    "learning", "base_checksum", "space_checksum", "origins"}
_LEAF_FIELDS = {"round_id", "silo_id", "base_checksum", "space_checksum", "sample_count", "rows_seen",
    "rows_excluded", "parameters", "checksum", "initial_objective", "objective", "output_id",
    "output_hash", "source_hash", "recipe_hash", "schema_fingerprint", "attempt_id", "generation",
    "contribution_id"}


def _encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("ascii")


def _digest(value) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()


def _hex(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("SHA256 정체성이 유효하지 않습니다")
    return value


def _text(value):
    if not isinstance(value, str) or not value:
        raise ValueError("비어 있지 않은 모델/특징 이름이 필요합니다")
    return value


def _version(value):
    _text(value)
    if len(value.split(".")) != 3 or not all(p.isdigit() for p in value.split(".")):
        raise ValueError("version은 SemVer 형식이어야 합니다")
    return value


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("유한한 숫자만 사용할 수 있습니다")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError("숫자 범위를 초과했습니다") from exc
    if not math.isfinite(number):
        raise ValueError("유한한 숫자만 사용할 수 있습니다")
    return number


def _vector(values, dimension):
    if not isinstance(values, list) or len(values) != dimension:
        raise ValueError("파라미터/입력 차원이 일치하지 않습니다")
    return [_number(value) for value in values]


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("표본 수/차원은 범위 내 정수여야 합니다")
    return value


def _features(values, target):
    if (not isinstance(values, list) or not values
            or any(not isinstance(value, str) or not value for value in values)
            or len(set(values)) != len(values) or _text(target) in values):
        raise ValueError("특징 순서/타깃 계약이 유효하지 않습니다")
    return list(values)


def _learning(value, features, target):
    keys = {"solver", "features", "target", "l2", "step_size", "steps", "initial_parameters"}
    if (not isinstance(value, dict) or set(value) != keys or value["solver"] != "ridge_gradient_v1"
            or value["features"] != features or value["target"] != target):
        raise ValueError("학습 solver/모델 공간 계약 불일치")
    if (_number(value["l2"]) < 0 or _number(value["step_size"]) <= 0
            or not 1 <= _integer(value["steps"], 1) <= 1000):
        raise ValueError("학습 solver 설정 범위 불일치")
    _vector(value["initial_parameters"], len(features) + 1)


def _origin(leaf, result):
    if not isinstance(leaf, dict) or set(leaf) != _LEAF_FIELDS:
        raise ValueError("원기여 필드 계약 불일치")
    body = {key: value for key, value in leaf.items() if key != "contribution_id"}
    if _digest(body) != _hex(leaf["contribution_id"]):
        raise ValueError("원기여 checksum 불일치")
    for key in ("round_id", "base_checksum", "space_checksum"):
        if leaf[key] != result[key]:
            raise ValueError("원기여와 확정 결과의 정체성 불일치")
    _text(leaf["silo_id"])
    parameters = _vector(leaf["parameters"], result["parameter_dim"])
    if _digest(parameters) != _hex(leaf["checksum"]):
        raise ValueError("원기여 파라미터 checksum 불일치")
    for key in ("output_id", "output_hash", "source_hash", "recipe_hash", "schema_fingerprint"):
        _hex(leaf[key])
    _integer(leaf["generation"])
    if leaf["attempt_id"] is not None:
        _text(leaf["attempt_id"])
    count = _integer(leaf["sample_count"], 1)
    if _integer(leaf["rows_seen"], 1) != count + _integer(leaf["rows_excluded"]):
        raise ValueError("원기여 유효 표본/제외 수 불일치")
    if any(_number(leaf[key]) < 0 for key in ("initial_objective", "objective")):
        raise ValueError("목적함수는 음수가 아니어야 합니다")


def _result(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, dict) or set(value) - _RESULT_FIELDS or value.get("format") != "ridge-v1":
        raise ValueError("확정된 ridge-v1 결과만 저장할 수 있습니다")
    # JSON 직렬화로 호출자의 mutable 상태와 분리하고 raw/임의 metadata를 거부한다.
    result = json.loads(_encoded(value))
    try:
        features = _features(result["features"], result["target"])
        _text(result["model_name"])
        _version(result["version"])
        _text(result["round_id"])
        dimension = _integer(result["parameter_dim"], 2)
        if dimension != len(features) + 1:
            raise ValueError("특징/편향 차원이 일치하지 않습니다")
        result["parameters"] = _vector(result["parameters"], dimension)
        if _digest(result["parameters"]) != _hex(result["checksum"]):
            raise ValueError("확정 파라미터 checksum 불일치")
        _hex(result["base_checksum"])
        _hex(result["space_checksum"])
        _learning(result["learning"], features, result["target"])
        origins = result["origins"]
        if not isinstance(origins, list) or not origins:
            raise ValueError("원기여 계보가 필요합니다")
        for leaf in origins:
            _origin(leaf, result)
        if len({leaf["silo_id"] for leaf in origins}) != len(origins):
            raise ValueError("중복 원기여를 저장할 수 없습니다")
        if sum(leaf["sample_count"] for leaf in origins) != _integer(result["total_samples"], 1):
            raise ValueError("전체 표본 수와 원기여 합계 불일치")
        if _integer(result["contributor_count"], 1) > len(origins):
            raise ValueError("대표 기여 수가 원기여 수보다 많습니다")
        identity = dict(round_id=result["round_id"], checksum=result["checksum"],
                        samples=result["total_samples"], origins=sorted(leaf["contribution_id"] for leaf in origins))
        if _digest(identity) != _hex(result["result_id"]):
            raise ValueError("확정 결과 result_id 불일치")
        preprocessing = sorted({(leaf["recipe_hash"], leaf["schema_fingerprint"]) for leaf in origins})
        settings = {key: item for key, item in result["learning"].items() if key != "initial_parameters"}
        if len(preprocessing) != 1 or _digest(dict(model_name=result["model_name"], version=result["version"],
                learning=settings, preprocessing=preprocessing)) != result["space_checksum"]:
            raise ValueError("전처리/학습 공간 checksum 불일치")
        result["origins"] = sorted(origins, key=lambda leaf: leaf["silo_id"])
        result.pop("aggregated_at", None)  # 같은 확정 결과의 재전달 시각은 저장 정체성에 영향을 주지 않는다.
        return result
    except (KeyError, TypeError) as exc:
        raise ValueError("확정 ridge 결과 필드가 누락되거나 잘못되었습니다") from exc


@dataclass(frozen=True)
class RidgeArtifact:
    directory: Path
    artifact_id: str
    manifest_sha256: str
    weights_sha256: str
    features: tuple[str, ...]
    target: str
    parameters: tuple[float, ...]
    _manifest_bytes: bytes

    @property
    def manifest(self):
        return json.loads(self._manifest_bytes)

    @property
    def weights_path(self):
        return self.directory / "weights.json"


def _json(data):
    def unique(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError("중복 JSON 필드를 허용하지 않습니다")
            values[key] = value
        return values
    return json.loads(data, object_pairs_hook=unique)


def load_artifact(root, artifact_id, *, expected_manifest_sha256=None):
    """저장 정체성·원본 결과·실제 weights를 모두 확인한 뒤 immutable 객체 반환."""
    directory = Path(root).resolve() / _hex(artifact_id)
    if directory.is_symlink():
        raise ValueError("artifact 경로에 심볼릭 링크를 사용할 수 없습니다")
    paths = [directory / name for name in ("manifest.json", "weights.json")]
    if any(path.is_symlink() for path in paths):
        raise ValueError("artifact 파일에 심볼릭 링크를 사용할 수 없습니다")
    manifest_bytes, weights_bytes = [path.read_bytes() for path in paths]
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if expected_manifest_sha256 is not None and manifest_hash != _hex(expected_manifest_sha256):
        raise ValueError("등록된 manifest checksum 불일치")
    manifest = _json(manifest_bytes)
    keys = {"artifact_format", "artifact_id", "model_name", "version", "source_result", "weights_file", "weights_sha256"}
    if not isinstance(manifest, dict) or set(manifest) != keys:
        raise ValueError("artifact manifest 필드 계약 불일치")
    body = {key: value for key, value in manifest.items() if key != "artifact_id"}
    if (manifest["artifact_format"] != "ridge-artifact-v1" or manifest["artifact_id"] != artifact_id
            or _digest(body) != artifact_id or manifest["weights_file"] != "weights.json"):
        raise ValueError("artifact manifest 정체성 불일치")
    result = _result(manifest["source_result"])
    if manifest["model_name"] != result["model_name"]:
        raise ValueError("등록 모델과 원본 결과의 이름 불일치")
    _version(manifest["version"])
    weights_hash = hashlib.sha256(weights_bytes).hexdigest()
    if weights_hash != _hex(manifest["weights_sha256"]):
        raise ValueError("실제 weights 파일 checksum 불일치")
    loaded_weights = _json(weights_bytes)
    if not isinstance(loaded_weights, dict) or loaded_weights != _weights(result):
        raise ValueError("실제 weights와 확정 모델 공간/파라미터 불일치")
    _vector(loaded_weights["parameters"], result["parameter_dim"])
    return RidgeArtifact(directory, artifact_id, manifest_hash, weights_hash, tuple(result["features"]),
                         result["target"], tuple(result["parameters"]), manifest_bytes)


def _weights(result):
    return {key: result[key] for key in ("format", "features", "target", "parameters", "parameter_dim", "checksum")}


def _sync_directory(directory):
    if os.name != "nt":
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write(path, data):
    with path.open("xb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def save_artifact(root, result, *, version=None):
    """완료 결과를 content address로 원자 게시. 동일 재전달은 덮어쓰지 않는다."""
    source = _result(result)
    weights = _encoded(_weights(source))
    body = dict(artifact_format="ridge-artifact-v1", model_name=source["model_name"],
                version=_version(version if version is not None else source["version"]), source_result=source,
                weights_file="weights.json", weights_sha256=hashlib.sha256(weights).hexdigest())
    artifact_id = _digest(body)
    manifest = _encoded(dict(body, artifact_id=artifact_id))
    root = Path(root).resolve()
    with _lock:
        root.mkdir(parents=True, exist_ok=True)
        destination = root / artifact_id
        if destination.exists() or destination.is_symlink():
            return load_artifact(root, artifact_id, expected_manifest_sha256=hashlib.sha256(manifest).hexdigest())
        staging = Path(tempfile.mkdtemp(prefix=".ridge-stage-", dir=root))
        try:
            _write(staging / "weights.json", weights)
            _write(staging / "manifest.json", manifest)
            _sync_directory(staging)
            try:
                os.rename(staging, destination)
            except OSError:
                # 다른 프로세스가 같은 정체성을 먼저 게시했을 때만 기존 bytes를 검증해 수락한다.
                if not destination.exists():
                    raise
                load_artifact(root, artifact_id, expected_manifest_sha256=hashlib.sha256(manifest).hexdigest())
            _sync_directory(root)
        finally:
            # 자신이 만든 staging의 알려진 두 파일만 정리한다. 기존 artifact는 절대 삭제하지 않는다.
            if staging.parent == root and staging.name.startswith(".ridge-stage-") and staging.exists():
                for name in ("weights.json", "manifest.json"):
                    (staging / name).unlink(missing_ok=True)
                staging.rmdir()
        return load_artifact(root, artifact_id, expected_manifest_sha256=hashlib.sha256(manifest).hexdigest())


def predict(artifact: RidgeArtifact, inputs):
    """명시 feature 순서의 batch 입력에 실제 w·x+b를 계산한다. 원시 입력은 기록하지 않는다."""
    features = _features(list(artifact.features), artifact.target)
    parameters = _vector(list(artifact.parameters), len(features) + 1)
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("비어 있지 않은 예측 입력 batch가 필요합니다")
    outputs = []
    for row in inputs:
        if isinstance(row, dict):
            if set(row) != set(features):
                raise ValueError("예측 feature 이름이 모델과 일치하지 않습니다")
            row = [row[feature] for feature in features]
        values = _vector(row, len(features))
        try:
            output = math.fsum([weight * value for weight, value in zip(parameters[:-1], values)] + [parameters[-1]])
        except (OverflowError, ValueError) as exc:
            raise ValueError("예측 계산이 유한한 범위를 벗어났습니다") from exc
        outputs.append(_number(output))
    return outputs
