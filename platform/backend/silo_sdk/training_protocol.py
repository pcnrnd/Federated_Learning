"""Live ridge 공통 wire 계약. 원시 행 없이 모델 공간/원기여를 검증한다."""
from __future__ import annotations

import hashlib
import json
import math


def encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("ascii")


def digest(value) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def vector(values, dimension=None):
    if not isinstance(values, list) or not values or (dimension is not None and len(values) != dimension):
        raise ValueError("학습 파라미터 차원 불일치")
    converted = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("파라미터는 유한한 숫자여야 합니다")
        try:
            number = float(value)
        except OverflowError as exc:
            raise ValueError("파라미터 범위 초과") from exc
        if not math.isfinite(number):
            raise ValueError("파라미터는 유한한 숫자여야 합니다")
        converted.append(number)
    return converted


def parameter_checksum(values) -> str:
    return digest(vector(values))


def participants(entry):
    roots = entry.get("member_snapshot") or []
    clusters = entry.get("cluster_snapshot") or {}
    return set(roots) | {node for group in clusters.values() for node in group}


def space_checksum(model_name, version, learning, outputs):
    settings = {k: v for k, v in learning.items() if k != "initial_parameters"}
    preprocessing = {(v["recipe_hash"], v["schema_fingerprint"]) for v in outputs.values()}
    if len(preprocessing) != 1:
        raise ValueError("live 참여자의 레시피/스키마 공간이 다릅니다")
    return digest({"model_name": model_name, "version": version, "learning": settings,
                   "preprocessing": sorted(preprocessing)})


def validate_round(entry):
    settings = entry["learning"]
    features = settings["features"]
    if (settings["solver"] != "ridge_gradient_v1" or not features or len(set(features)) != len(features)
            or settings["target"] in features or any(not isinstance(f, str) or not f for f in features)):
        raise ValueError("live 모델 공간 계약이 유효하지 않습니다")
    for key in ("l2", "step_size"):
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("유한한 solver 설정이 필요합니다")
    if (settings["l2"] < 0 or settings["step_size"] <= 0 or type(settings["steps"]) is not int
            or not 1 <= settings["steps"] <= 1000):
        raise ValueError("solver 설정 범위 불일치")
    base = vector(entry["base_parameters"], len(features) + 1)
    if parameter_checksum(base) != entry["base_checksum"]:
        raise ValueError("전역 초기값 checksum 불일치")
    expected_space = space_checksum(entry["model_name"], entry["version"], settings,
        {node: entry["cleaning_snapshot"][node] for node in participants(entry)})
    if expected_space != entry["space_checksum"]:
        raise ValueError("모델 공간 checksum 불일치")


LEAF_FIELDS = {"round_id", "silo_id", "base_checksum", "space_checksum", "sample_count",
    "rows_seen", "rows_excluded", "parameters", "checksum", "initial_objective", "objective",
    "output_id", "output_hash", "source_hash", "recipe_hash", "schema_fingerprint",
    "attempt_id", "generation", "contribution_id"}


def make_leaf(entry, silo_id, result):
    reference = entry["cleaning_snapshot"][silo_id]
    body = {"round_id": entry["round_id"], "silo_id": silo_id,
        "base_checksum": entry["base_checksum"], "space_checksum": entry["space_checksum"],
        "sample_count": result.sample_count, "rows_seen": result.rows_seen,
        "rows_excluded": result.rows_excluded, "parameters": result.parameters,
        "checksum": parameter_checksum(result.parameters),
        "initial_objective": result.initial_objective, "objective": result.objective,
        **{key: reference[key] for key in ("output_id", "output_hash", "source_hash", "recipe_hash",
                                          "schema_fingerprint", "attempt_id", "generation")}}
    body["contribution_id"] = digest(body)
    validate_leaf(entry, body)
    return body


def validate_leaf(entry, leaf):
    if not isinstance(leaf, dict) or set(leaf) != LEAF_FIELDS:
        raise ValueError("원기여 필드가 wire 계약과 다릅니다")
    silo_id = leaf["silo_id"]
    if silo_id not in participants(entry):
        raise ValueError("참여 스냅샷에 없는 원기여")
    for key in ("round_id", "base_checksum", "space_checksum"):
        if leaf[key] != entry[key]:
            raise ValueError(f"원기여 {key} 불일치")
    reference = entry["cleaning_snapshot"][silo_id]
    for key in ("output_id", "output_hash", "source_hash", "recipe_hash", "schema_fingerprint",
                "attempt_id", "generation"):
        if leaf[key] != reference[key]:
            raise ValueError(f"원기여 정제 {key} 불일치")
    for key in ("sample_count", "rows_seen", "rows_excluded"):
        if type(leaf[key]) is not int or leaf[key] < 0:
            raise ValueError("표본/제외 수는 음수가 아닌 정수여야 합니다")
    if (leaf["sample_count"] < 1 or leaf["rows_seen"] != reference["rows_out"]
            or leaf["sample_count"] + leaf["rows_excluded"] != leaf["rows_seen"]):
        raise ValueError("정제 출력과 실제 유효 표본/제외 수 불일치")
    for key in ("initial_objective", "objective"):
        if isinstance(leaf[key], bool) or not isinstance(leaf[key], (int, float)) or leaf[key] < 0:
            raise ValueError("유한한 목적함수가 필요합니다")
        vector([leaf[key]])
    values = vector(leaf["parameters"], len(entry["learning"]["features"]) + 1)
    if leaf["checksum"] != parameter_checksum(values):
        raise ValueError("원기여 파라미터 checksum 불일치")
    if leaf["contribution_id"] != digest({k: v for k, v in leaf.items() if k != "contribution_id"}):
        raise ValueError("원기여 식별/checksum 불일치")
    return leaf


def weighted(leaves):
    total = sum(leaf["sample_count"] for leaf in leaves)
    dimension = len(leaves[0]["parameters"])
    values = [math.fsum(leaf["sample_count"] / total * leaf["parameters"][j] for leaf in leaves)
              for j in range(dimension)]
    return total, vector(values, dimension)


def combine_live(entry, silo_id, leaves):
    if silo_id not in entry["member_snapshot"]:
        raise ValueError("중앙 대표 제출자가 아닙니다")
    expected = {silo_id, *(entry.get("cluster_snapshot") or {}).get(silo_id, [])}
    identities = [leaf["silo_id"] for leaf in leaves]
    if len(set(identities)) != len(identities) or set(identities) != expected:
        raise ValueError("집계자 자기/정확한 하위 원기여가 필요합니다")
    leaves = sorted((validate_leaf(entry, leaf) for leaf in leaves), key=lambda leaf: leaf["silo_id"])
    total, parameters = weighted(leaves)
    result = {"round_id": entry["round_id"], "silo_id": silo_id, "sample_count": total,
        "parameters": parameters, "checksum": parameter_checksum(parameters),
        "aggregated_from": sorted(expected - {silo_id}), "origins": leaves,
        "base_checksum": entry["base_checksum"], "space_checksum": entry["space_checksum"]}
    result["envelope_checksum"] = digest(result)
    return result


def validate_envelope(entry, envelope):
    validate_round(entry)
    rebuilt = combine_live(entry, envelope["silo_id"], envelope["origins"])
    for key, expected in rebuilt.items():
        if envelope.get(key) != expected:
            raise ValueError(f"대표 기여 {key} 불일치")
    return rebuilt
