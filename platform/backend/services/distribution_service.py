"""분포 설정·보고서·current·명시적 baseline을 한 원자적 원장으로 보존한다."""
from __future__ import annotations

import threading
from datetime import datetime

import yaml
from fastapi import HTTPException

from config import settings
from silo_sdk.distributions import REPORT_FIELDS, configure, fingerprint, sha, validate_report
from storage.factory import StorageDomain, get_repository
from storage.settings import get_backend

_lock = threading.RLock()
_SECTIONS = ("configs", "reports", "current", "baselines", "baseline_current")


def _repository():
    return get_repository(StorageDomain.DISTRIBUTIONS, settings.CONFIG_DIR / "distributions.yaml")


def _load() -> dict:
    # legacy YAML loader의 손상→빈 dict 처리를 신규 원장에는 적용하지 않는다.
    path = settings.CONFIG_DIR / "distributions.yaml"
    try:
        existing_yaml = get_backend() == "yaml" and path.exists()
        if existing_yaml:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        else:
            document = _repository().load()
        if not isinstance(document, dict):
            raise ValueError()
        if not document:
            if existing_yaml:
                raise ValueError()
            return {key: {} for key in _SECTIONS}
        state = document["state"]
        if set(state) != set(_SECTIONS) or any(not isinstance(state[k], dict) for k in _SECTIONS):
            raise ValueError()
        return state
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise HTTPException(503, "분포 원장을 읽을 수 없습니다") from exc


def _save(state: dict) -> None:
    _repository().save({"state": state})  # 보고서와 current/기준 포인터는 한 번에 commit.


def _required(state: dict, section: str, identity: str) -> dict:
    item = state[section].get(identity)
    if item is None:
        raise HTTPException(404, "분포 설정/관측/기준이 없습니다")
    return item


def create_config(definition: dict) -> dict:
    from config.server_manager import load_servers
    from services import cleaning_recipe_service, model_registry
    try:
        config = configure(definition)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "분포 설정 계약이 유효하지 않습니다") from exc
    model = model_registry.get_model(config["model_name"], config["version"])
    known = {"feature_columns": model.metadata.get("features", model.input_schema.get("features")),
             "target_column": model.metadata.get("target", model.output_schema.get("target"))}
    for key, value in known.items():
        if value is not None and config[key] != value:
            raise HTTPException(422, "분포 설정과 모델의 학습 행 계약이 불일치합니다")
    if not set(config["node_ids"]) <= set(load_servers()):
        raise HTTPException(422, "등록되지 않은 분포 수집 사일로입니다")
    recipe = cleaning_recipe_service.get_recipe(config["recipe_name"], config["recipe_version"])
    mapping = recipe.mapping
    if config["recipe_hash"] != sha(recipe.model_dump(mode="json")):
        raise HTTPException(422, "분포 설정 레시피 지문 불일치")
    if mapping and (config["feature"] == mapping.key or config["feature"] not in mapping.common_schema):
        raise HTTPException(422, "수집 가능한 공통 feature가 아닙니다")
    with _lock:
        state = _load()
        previous = state["configs"].get(config["config_id"])
        if previous is not None:
            return previous
        state["configs"][config["config_id"]] = config
        _save(state)
    return config


def list_configs(node_id: str | None = None) -> list[dict]:
    with _lock:
        configs = _load()["configs"].values()
        return [c for c in configs if node_id is None or node_id in c["node_ids"]]


def _check_output(body: dict, config: dict) -> None:
    from services.cleaning_job_service import get_job
    job = get_job(body["job_id"])
    matches = [s for s in job.shards if s.shard_index == body["shard_index"]]
    if not matches:
        raise HTTPException(409, "분포 출력 배정이 없습니다")
    shard = matches[0]
    valid = (shard.status == "completed" and shard.silo_id == body["node_id"]
        and job.generation == body["generation"] and shard.rows_out == body["total_count"]
        and job.recipe_name == config["recipe_name"] and job.recipe_version == config["recipe_version"])
    fields = ("attempt_id", "output_id", "output_hash", "source_hash", "recipe_hash",
              "schema_fingerprint", "completed_at")
    if not valid or any(getattr(shard, k) != body[k] for k in fields):
        raise HTTPException(409, "분포 출력은 중앙의 성공 정제 계보와 불일치합니다")


def accept_report(body: dict) -> dict:
    if set(body) != REPORT_FIELDS or not fingerprint(body.get("config_id")):
        raise HTTPException(422, "분포 보고서 필드가 유효하지 않습니다")
    with _lock:
        state = _load()
        config = _required(state, "configs", body.get("config_id", ""))
        try:
            validate_report(body, config)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise HTTPException(422, "분포 보고서 계약이 유효하지 않습니다") from exc
        previous = state["reports"].get(body["report_id"])
        if previous is not None:
            if previous != body:
                raise HTTPException(409, "같은 분포 보고서 ID에 상충하는 내용입니다")
            return _ack(previous)  # 정제 generation이 바뀌어도 저장된 ACK는 재전송 가능.
        _check_output(body, config)
        state["reports"][body["report_id"]] = dict(body)
        key = sha([body["config_id"], body["node_id"]])
        old = state["reports"].get(state["current"].get(key, ""))
        if old is None or _order(body) > _order(old):
            state["current"][key] = body["report_id"]
        _save(state)
        return _ack(body)


def _ack(body: dict) -> dict:
    return {"report_id": body["report_id"], "report_hash": body["report_hash"], "accepted": True}


def _order(body: dict) -> tuple:
    return datetime.fromisoformat(body["completed_at"]), body["output_id"]


def get_report(report_id: str) -> dict:
    with _lock:
        return _required(_load(), "reports", report_id)


def get_current(config_id: str, node_id: str, *, baseline=False) -> dict:
    with _lock:
        state = _load()
        config = _required(state, "configs", config_id)
        if node_id not in config["node_ids"]:
            raise HTTPException(422, "설정 범위 밖 사일로입니다")
        section = "baseline_current" if baseline else "current"
        identity = state[section].get(sha([config_id, node_id]), "")
        return _required(state, "baselines" if baseline else "reports", identity)


def select_baseline(report_id: str) -> dict:
    with _lock:
        state = _load()
        report = _required(state, "reports", report_id)
        baseline = {"baseline_id": sha(["baseline-v1", report_id]), "report_id": report_id,
                    "config_id": report["config_id"], "node_id": report["node_id"], "report": report}
        state["baselines"][baseline["baseline_id"]] = baseline
        state["baseline_current"][sha([report["config_id"], report["node_id"]])] = baseline["baseline_id"]
        _save(state)
        return baseline


def get_baseline(baseline_id: str) -> dict:
    with _lock:
        return _required(_load(), "baselines", baseline_id)
