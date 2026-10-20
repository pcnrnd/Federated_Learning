"""불변 재교육 설정과 모델 참조 예약. 잠금 순서는 registry→분포 원장이다."""
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import HTTPException

from models.retraining_schemas import RetrainConfigRequest
from services import distribution_service as ledger, model_registry, silo_group_service
from silo_sdk.distributions import sha


def topology(group_id):
    roots = list(silo_group_service.get_group(group_id).member_node_ids)
    groups = silo_group_service.list_groups()
    selected = [g for g in groups if g.aggregator_node_id in roots]
    clusters = {g.aggregator_node_id: list(g.member_node_ids) for g in selected}
    leaves = [node for members in clusters.values() for node in members]
    if (not roots or len(set(roots)) != len(roots) or len(clusters) != len(selected)
            or len(set(leaves)) != len(leaves) or set(roots) & set(leaves)
            or any(g.aggregator_node_id in leaves for g in groups)):
        raise HTTPException(409, "재교육은 중복 없는 root/leaf 2단계 범위여야 합니다")
    return {"roots": roots, "clusters": clusters, "nodes": sorted([*roots, *leaves])}


def _definition(body, state):
    distribution = ledger._required(state, "configs", body["config_id"])
    policy = ledger._required(state, "drift_policies", body["policy_id"])
    if (policy["config_id"] != body["config_id"]
            or state["drift_policy_current"].get(body["config_id"]) != body["policy_id"]):
        raise HTTPException(409, "현재 저장된 분포 정책을 선택하세요")
    entry = model_registry.get_model(distribution["model_name"], distribution["version"])
    if entry.status != "active":
        raise HTTPException(409, "활성 모델 버전만 재교육 기준으로 예약할 수 있습니다")
    artifact = model_registry.get_ridge_artifact(entry)
    if list(artifact.features) != distribution["feature_columns"] or artifact.target != distribution["target_column"]:
        raise HTTPException(409, "재교육 기준 artifact와 분포 feature/target 순서가 다릅니다")
    from services import cleaning_recipe_service
    recipe = cleaning_recipe_service.get_recipe(distribution["recipe_name"], distribution["recipe_version"])
    if sha(recipe.model_dump(mode="json")) != distribution["recipe_hash"]:
        raise HTTPException(409, "재교육 레시피의 현재 지문이 다릅니다")
    scope = topology(body["group_id"])
    if set(scope["nodes"]) != set(distribution["node_ids"]):
        raise HTTPException(409, "분포 설정과 재교육 root/leaf 범위가 정확히 같아야 합니다")
    endpoints = body["worker_endpoints"] or {node: f"http://{node}:8081" for node in scope["nodes"]}
    if set(endpoints) != set(scope["nodes"]):
        raise HTTPException(422, "전체 root/leaf worker 주소가 필요합니다")
    for endpoint in endpoints.values():
        try:
            parsed = urlparse(endpoint)
            valid = (parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment
                and parsed.path in ("", "/") and parsed.port != 2375)
        except ValueError:
            valid = False
        if not valid:
            raise HTTPException(422, "재교육 HTTP worker 주소가 유효하지 않습니다")
    return dict(body, worker_endpoints=endpoints, topology=scope, model_name=entry.name, version=entry.version,
        artifact_id=artifact.artifact_id, manifest_sha256=artifact.manifest_sha256,
        weights_sha256=artifact.weights_sha256, recipe_name=recipe.name, recipe_version=recipe.version,
        recipe_hash=distribution["recipe_hash"], schema_fingerprint=distribution["schema_fingerprint"],
        live_learning=dict(body["learning"], solver="ridge_gradient_v1", features=list(artifact.features),
                           target=artifact.target, initial_parameters=list(artifact.parameters)))


def put_config(body):
    value = RetrainConfigRequest(**body).model_dump(mode="json")
    with model_registry.REGISTRY_LOCK, ledger._lock:
        state = ledger._load()
        definition = _definition(value, state)
        previous = state["retrain_configs"].get(state["retrain_config_current"].get(value["config_id"], ""))
        if previous and previous["definition"] == definition:
            return previous
        version = previous["config_version"] + 1 if previous else 1
        config = dict(retrain_config_id=sha(["retrain-config-v1", version, definition]), config_version=version,
                      definition=definition, created_at=datetime.now(timezone.utc).isoformat())
        state["retrain_configs"][config["retrain_config_id"]] = config
        state["retrain_config_current"][value["config_id"]] = config["retrain_config_id"]
        ledger._save(state)
        return config


def references(name, version, result_id=None):
    """호출자는 registry lock을 보유한다. 실패/미확인 intent도 복구 전 숨기지 않는다."""
    with ledger._lock:
        state = ledger._load()
        active = [state["retrain_configs"][identity]["definition"]
                  for identity in state["retrain_config_current"].values()]
        if any(c["enabled"] and (c["model_name"], c["version"]) == (name, version) for c in active):
            return True
        for event in state["retrain_events"].values():
            if event["status"] == "registered":
                continue
            if event["status"] == "failed" and not event["references_pending"]:
                continue
            definition = state["retrain_configs"][event["retrain_config_id"]]["definition"]
            if ((definition["model_name"], definition["version"]) == (name, version)
                    or result_id and (event.get("final_result_id") == result_id
                                      or result_id in event["registration_result_ids"])):
                return True
    return False
