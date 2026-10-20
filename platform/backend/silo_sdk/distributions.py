"""정제 출력 분포의 공통 계약. 행은 로컬에서만 읽고 카운트만 반환한다."""
from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timezone

from .cleaning_output import digest, encoded
from .histograms import build_histogram
from .iterative_ridge import _data_number

CONFIG_FIELDS = frozenset(("model_name", "version", "node_ids", "feature", "bin_edges",
    "schema_fingerprint", "recipe_name", "recipe_version", "recipe_hash", "target_column",
    "entity_id_columns", "feature_columns", "window_seconds"))
REPORT_FIELDS = frozenset(("report_id", "report_hash", "config_id", "config_hash", "bin_hash",
    "node_id", "feature", "schema_fingerprint", "recipe_hash", "job_id", "generation",
    "shard_index", "attempt_id", "output_id", "output_hash", "source_hash", "completed_at",
    "window_start", "window_end", "bin_edges", "bin_counts", "total_count", "valid_count",
    "excluded_count"))
HASH_FIELDS = ("schema_fingerprint", "recipe_hash", "output_id", "output_hash", "source_hash")


def sha(value) -> str:
    return digest(encoded(value))


def fingerprint(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def natural(value, *, positive=False) -> bool:
    return type(value) is int and value >= (1 if positive else 0)


def edges(values) -> list[float]:
    if not isinstance(values, list) or not 2 <= len(values) <= 1025:
        raise ValueError("분포 구간 수가 유효하지 않습니다")
    try:
        valid = all(type(v) in (int, float) and math.isfinite(v) for v in values)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("분포 경계는 유한한 숫자여야 합니다")
    result = [float(v) for v in values]
    if any(a >= b for a, b in zip(result, result[1:])):
        raise ValueError("분포 경계는 엄격히 증가해야 합니다")
    return result


def configure(definition: dict) -> dict:
    if set(definition) != CONFIG_FIELDS:
        raise ValueError("분포 설정 필드가 유효하지 않습니다")
    data = dict(definition, bin_edges=edges(definition["bin_edges"]))
    names = ("model_name", "version", "feature", "recipe_name", "recipe_version", "target_column")
    if any(not isinstance(data[k], str) or not data[k].strip() or len(data[k]) > 200 for k in names):
        raise ValueError("분포 설정 이름이 유효하지 않습니다")
    for key in ("node_ids", "entity_id_columns", "feature_columns"):
        items = data[key]
        if not isinstance(items, list) or not items or len(items) != len(set(items)):
            raise ValueError("분포 설정 범위가 유효하지 않습니다")
        if any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in items):
            raise ValueError("분포 설정 범위가 유효하지 않습니다")
        data[key] = list(items) if key == "feature_columns" else sorted(items)
    if (data["feature"] not in data["feature_columns"]
            or set(data["feature_columns"]) & {data["target_column"], *data["entity_id_columns"]}):
        raise ValueError("타깃/엔터티 식별자 분포는 수집할 수 없습니다")
    if not all(fingerprint(data[k]) for k in ("schema_fingerprint", "recipe_hash")):
        raise ValueError("분포 설정 지문이 유효하지 않습니다")
    if not natural(data["window_seconds"], positive=True) or data["window_seconds"] > 86400:
        raise ValueError("분포 관측 창은 1~86400초여야 합니다")
    identity = sha(data)
    return dict(data, config_id=identity, config_hash=identity,
                bin_hash=sha({"edges": data["bin_edges"], "closure": "left-closed-clip-v1"}))


def validate_config(config: dict) -> dict:
    if set(config) != CONFIG_FIELDS | {"config_id", "config_hash", "bin_hash"}:
        raise ValueError("분포 설정 계약 불일치")
    expected = configure({k: config[k] for k in CONFIG_FIELDS})
    if expected != config:
        raise ValueError("분포 설정 해시 불일치")
    return expected


def window(completed_at: str, seconds: int) -> tuple[str, str]:
    at = datetime.fromisoformat(completed_at)
    if at.tzinfo is None:
        raise ValueError("분포 관측 시각에 시간대가 필요합니다")
    start = math.floor(at.timestamp() / seconds) * seconds
    return tuple(datetime.fromtimestamp(t, timezone.utc).isoformat() for t in (start, start + seconds))


def histogram(rows: list[dict], feature: str, bin_edges: list, *,
              feature_columns: list[str] | None = None, target_column: str | None = None) -> dict:
    """N은 전체 출력 행, valid/excluded는 학습과 같은 전체 feature+target 유효 행이다."""
    numeric = []
    columns = [*(feature_columns or [feature]), *([target_column] if target_column else [])]
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if all(_data_number(row.get(column)) is not None for column in columns):
            numeric.append(_data_number(row.get(feature)))
    counts = build_histogram(numeric, edges(bin_edges))
    return {"bin_counts": counts, "total_count": len(rows), "valid_count": len(numeric),
            "excluded_count": len(rows) - len(numeric)}


def report_identity(report: dict) -> str:
    return sha({k: report[k] for k in ("node_id", "output_id", "output_hash", "config_id",
        "feature", "window_start", "window_end")})


def build_report(rows: list[dict], manifest: dict, config: dict, shard: dict) -> dict:
    config = validate_config(config)
    start, end = window(shard["completed_at"], config["window_seconds"])
    body = {k: config[k] for k in ("config_id", "config_hash", "bin_hash", "feature", "bin_edges")}
    body.update({k: manifest[k] for k in (*HASH_FIELDS, "job_id", "generation", "attempt_id")})
    body.update(node_id=manifest["silo_id"], shard_index=shard["shard_index"],
                completed_at=shard["completed_at"], window_start=start, window_end=end)
    body.update(histogram(rows, config["feature"], config["bin_edges"],
                          feature_columns=config["feature_columns"], target_column=config["target_column"]))
    body["report_id"] = report_identity(body)
    body["report_hash"] = sha(body)
    validate_report(body, config)
    return body


def validate_report(body: dict, config: dict) -> None:
    validate_config(config)
    if set(body) != REPORT_FIELDS:
        raise ValueError("분포 보고서 필드가 유효하지 않습니다")
    for key in ("config_id", "config_hash", "bin_hash", "feature", "bin_edges",
                "schema_fingerprint", "recipe_hash"):
        if body[key] != config[key]:
            raise ValueError("분포 설정/출력 계약 불일치")
    if body["node_id"] not in config["node_ids"] or not all(fingerprint(body[k]) for k in HASH_FIELDS):
        raise ValueError("분포 보고 범위/지문 불일치")
    counts = body["bin_counts"]
    if (not isinstance(counts, list) or len(counts) != len(config["bin_edges"]) - 1
            or not all(natural(n) for n in counts)):
        raise ValueError("분포 카운트가 유효하지 않습니다")
    if not all(natural(body[k]) for k in ("generation", "shard_index", "excluded_count")):
        raise ValueError("분포 정수 통계가 유효하지 않습니다")
    if (not natural(body["total_count"], positive=True) or not natural(body["valid_count"], positive=True)
            or sum(counts) != body["valid_count"]
            or body["valid_count"] + body["excluded_count"] != body["total_count"]):
        raise ValueError("분포 표본이 없거나 카운트 합계가 불일치합니다")
    if not all(isinstance(body[k], str) and body[k] for k in ("job_id", "attempt_id", "completed_at")):
        raise ValueError("분포 출력 계보가 유효하지 않습니다")
    if (body["window_start"], body["window_end"]) != window(body["completed_at"], config["window_seconds"]):
        raise ValueError("분포 관측 창 불일치")
    if (body["report_id"] != report_identity(body)
            or body["report_hash"] != sha({k: v for k, v in body.items() if k != "report_hash"})):
        raise ValueError("분포 보고서 식별자/해시 불일치")
