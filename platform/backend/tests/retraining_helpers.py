"""실제 로컬 정제/카운트와 불변 ridge 기준을 제공하는 재교육 시험 fixture."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from config.server_manager import save_servers
from models.cleaning_schemas import CleaningJobCreate, CleaningRecipeRequest, ShardReport
from models.federated_schemas import SiloGroupRequest
from models.packaging_schemas import ModelRegisterRequest
from services import cleaning_job_service as clean, cleaning_recipe_service as recipes
from services import distribution_service as distribution, distribution_drift as drift
from services import model_registry, ridge_artifacts, silo_group_service
from silo_sdk.cleaning_output import execute, load_output
from silo_sdk.distributions import build_report, sha

PRIVATE = "private-entity-retraining-should-never-reach-central"
TARGET = 987654.321098765


def clean_local(world, job_id):
    manifests = {}
    for assigned in clean.get_job(job_id).shards:
        node = assigned.silo_id
        job = clean.start_shard(job_id, assigned.shard_index, node, job_id + node)
        shard = job.shards[assigned.shard_index]
        manifest = execute(str(world.data[node]), node, job.model_dump(), shard.model_dump(), world.recipe)
        fields = {key: manifest[key] for key in ("rows_in", "rows_out", "step_counters", "schema_fingerprint",
                  "output_id", "output_hash", "source_hash", "recipe_hash")}
        clean.report_shard(ShardReport(job_id=job_id, shard_index=assigned.shard_index, silo_id=node,
            attempt_id=shard.attempt_id, started_at=shard.started_at, completed_at=world.at, **fields))
        manifests[node] = manifest
    return manifests


def publish(world, job_id, manifest, *, baseline=False):
    node = world.nodes[0]
    rows, stored = load_output(str(world.data[node]), manifest[node])
    shard = next(s for s in clean.get_job(job_id).shards if s.silo_id == node)
    report = build_report(rows, stored, world.distribution, shard.model_dump())
    distribution.accept_report(report)
    if baseline:
        distribution.select_baseline(report["report_id"])
    return report


def setup_world(tmp_path, result, *, hierarchy=False):
    nodes = [f"silo-{n}" for n in range(1, 7 if hierarchy else 3)]
    roots = [nodes[0], nodes[3]] if hierarchy else nodes
    save_servers({n: {"base_url": f"tcp://{n}:2375", "role": "client"} for n in nodes})
    silo_group_service.create_group(SiloGroupRequest(group_id="retrain-group", member_node_ids=roots))
    if hierarchy:
        for name, root, leaves in (("left", nodes[0], nodes[1:3]), ("right", nodes[3], nodes[4:6])):
            silo_group_service.create_group(SiloGroupRequest(group_id=name, aggregator_node_id=root, member_node_ids=leaves))
    artifact = ridge_artifacts.save_artifact(tmp_path / "base-artifacts", result)
    model_registry.register_model(ModelRegisterRequest(name=result["model_name"], version=result["version"],
        framework="ridge", weights_path=str(artifact.weights_path)))
    recipe = recipes.register_recipe(CleaningRecipeRequest(name="retrain-recipe", version="1.0.0", steps=[
        {"type": "trim_whitespace", "params": {"columns": ["x1"]}}, {"type": "dedupe", "params": {"keys": ["id"]}}]))
    data = {}
    for node in nodes:
        directory = tmp_path / node
        directory.mkdir()
        rows = [dict(id=PRIVATE + str(n), x1=str(n), x2=0.25, x3=0.5, y=TARGET) for n in range(1, 5)]
        (directory / "input.json").write_text(json.dumps([*rows, rows[0]]), encoding="utf-8")
        data[node] = directory
    world = SimpleNamespace(nodes=nodes, roots=roots, data=data, recipe=recipe.model_dump(mode="json"), artifact=artifact,
        at=(datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat())
    clean.create_job(CleaningJobCreate(job_id="retrain-baseline", recipe_name=recipe.name, recipe_version=recipe.version,
                                      group_id="retrain-group", dataset_label="input"))
    manifests = clean_local(world, "retrain-baseline")
    world.baseline_manifests = manifests
    world.distribution = distribution.create_config(dict(model_name=result["model_name"], version=result["version"],
        node_ids=nodes, feature="x1", feature_columns=["x1", "x2", "x3"], target_column="y", entity_id_columns=["id"],
        bin_edges=[0, 10, 100], schema_fingerprint=manifests[nodes[0]]["schema_fingerprint"],
        recipe_name=recipe.name, recipe_version=recipe.version, recipe_hash=sha(world.recipe), window_seconds=60))
    publish(world, "retrain-baseline", manifests, baseline=True)
    world.policy = drift.put_policy(dict(config_id=world.distribution["config_id"], warning_threshold=.1,
        critical_threshold=.2, min_valid_count=2, max_age_seconds=3600))
    return world


def config_body(world, **updates):
    body = dict(config_id=world.distribution["config_id"], policy_id=world.policy["policy_id"], group_id="retrain-group",
        dataset_label="input", max_rounds=2, enabled=True, auto_enabled=False)
    return dict(body, **updates)
