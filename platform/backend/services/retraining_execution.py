"""기존 정제→live 학습→불변 artifact 등록을 고정 intent에 재연결한다."""
from fastapi import HTTPException

from models.cleaning_schemas import CleaningJobCreate
from models.federated_schemas import TrainingJobRequest
from services import cleaning_job_service as cleaning, training_job_service as training
from services import distribution_service as ledger, retraining_config as configs, retraining_service as events
from services import model_registry, training_model_service, training_round_service as rounds
from silo_sdk import training_protocol as wire


class ContractError(Exception):
    """원시 값/예외 본문을 원장에 쓰지 않는 고정 오류 코드."""

    def __init__(self, code, *, references_pending=True):
        super().__init__(code)
        self.references_pending = references_pending


def _config(event):
    with ledger._lock:
        return ledger._required(ledger._load(), "retrain_configs", event["retrain_config_id"])["definition"]


def _topology(definition):
    try:
        actual = configs.topology(definition["group_id"])
    except HTTPException as exc:
        if exc.status_code in (400, 404, 409):
            raise ContractError("topology_changed") from exc
        raise
    if actual != definition["topology"]:
        raise ContractError("topology_changed")


def _same_request(job, request):
    expected = request.model_dump(mode="json")
    if job.model_dump(mode="json", include=set(expected)) != expected:
        raise ContractError("child_request_conflict")
    return job


def _ensure(service, request):
    try:
        return _same_request(service.get_job(request.job_id), request)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    try:
        return _same_request(service.create_job(request), request)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        # 응답 유실/경쟁의 409는 존재만으로 성공 취급하지 않는다.
        return _same_request(service.get_job(request.job_id), request)


def _snapshot(event, definition):
    from services.cleaning_execution import require_training_output
    job = require_training_output(event["cleaning_request"]["job_id"])
    _same_request(job, CleaningJobCreate(**event["cleaning_request"]))
    if job.generation != event["cleaning_generation"]:
        raise ContractError("cleaning_generation_conflict")
    rows = {s.silo_id: dict(s.model_dump(include={"output_id", "output_hash", "source_hash", "recipe_hash",
        "schema_fingerprint", "attempt_id", "rows_in", "rows_out"}), generation=job.generation,
        recipe_name=job.recipe_name, recipe_version=job.recipe_version) for s in job.shards}
    if (len(rows) != len(job.shards) or set(rows) != set(definition["topology"]["nodes"])
            or any(row["recipe_hash"] != definition["recipe_hash"]
                   or row["schema_fingerprint"] != definition["schema_fingerprint"] for row in rows.values())):
        raise ContractError("cleaning_snapshot_conflict")
    if event["cleaning_snapshot"] is not None and event["cleaning_snapshot"] != rows:
        raise ContractError("successful_output_changed")
    return rows


def _clean_intent(event, definition):
    _topology(definition)
    from services import cleaning_recipe_service
    from silo_sdk.distributions import sha
    recipe = cleaning_recipe_service.get_recipe(definition["recipe_name"], definition["recipe_version"])
    if sha(recipe.model_dump(mode="json")) != definition["recipe_hash"]:
        raise ContractError("recipe_changed")
    job = _ensure(cleaning, CleaningJobCreate(**event["cleaning_request"]))
    if sorted(s.silo_id for s in job.shards) != definition["topology"]["nodes"]:
        raise ContractError("cleaning_scope_conflict")
    return events.update(event["event_id"], status="wait_cleaning", error_code=None)


def _wait_clean(event, definition):
    _topology(definition)
    # reschedule과 같은 job→ledger 순서로 읽기/예약을 묶는다. registry/외부 생성 I/O는 없다.
    with cleaning._lock:
        job = cleaning.get_job(event["cleaning_request"]["job_id"])
        if job.generation != event["cleaning_generation"]:
            raise ContractError("cleaning_generation_conflict")
        if job.status in ("failed", "cancelled"):
            raise ContractError("cleaning_failed")
        if job.status != "completed":
            return events.update(event["event_id"], error_code=None)
        snapshot = _snapshot(event, definition)
        return events.update(event["event_id"], status="training_intent", cleaning_snapshot=snapshot, error_code=None)


def _train_intent(event, definition):
    _snapshot(event, definition)
    _topology(definition)
    _ensure(training, TrainingJobRequest(**event["training_request"]))
    return events.update(event["event_id"], status="training", error_code=None)


def _results(event, definition):
    entries = sorted((r for r in rounds.list_rounds() if r.job_id == event["training_request"]["job_id"]),
                     key=lambda r: r.job_occurrence or 0)
    if [r.job_occurrence for r in entries] != list(range(1, definition["max_rounds"] + 1)):
        raise ContractError("round_occurrence_conflict")
    previous = None
    base = definition["live_learning"]["initial_parameters"]
    for entry in entries:
        if (entry.status != "completed" or entry.member_snapshot != definition["topology"]["roots"]
                or entry.cluster_snapshot != definition["topology"]["clusters"]
                or entry.cleaning_snapshot != event["cleaning_snapshot"]
                or entry.cleaning_job_id != event["cleaning_request"]["job_id"]
                or entry.model_name != definition["model_name"] or entry.version != definition["version"]
                or entry.parent_round_id != previous or entry.base_parameters != base or entry.learning is None
                or entry.learning.model_dump(mode="json") != definition["live_learning"]):
            raise ContractError("round_lineage_conflict")
        result = rounds.get_result(entry.round_id)
        if result.base_checksum != wire.parameter_checksum(base):
            raise ContractError("global_feedback_conflict")
        if (set(leaf["silo_id"] for leaf in result.origins or []) != set(event["cleaning_snapshot"])
                or len(result.origins or []) != len(event["cleaning_snapshot"])):
            raise ContractError("result_origin_conflict")
        for leaf in result.origins:
            wire.validate_leaf(entry.model_dump(mode="json"), leaf)
        previous, base = entry.round_id, result.parameters
    return entries, result


def _wait_training(event, definition):
    job = _same_request(training.get_job(event["training_request"]["job_id"]),
                        TrainingJobRequest(**event["training_request"]))
    if job.status in ("failed", "cancelled") or job.rounds_failed:
        raise ContractError("training_failed", references_pending=job.current_round_id is not None)
    if job.status != "completed":
        return events.update(event["event_id"], error_code=None)
    if job.rounds_completed != definition["max_rounds"] or job.current_round_id or job.opening_intent:
        raise ContractError("training_completion_conflict")
    _snapshot(event, definition)
    entries, result = _results(event, definition)
    return events.update(event["event_id"], status="wait_registration", round_ids=[r.round_id for r in entries],
                         final_result_id=result.result_id, error_code=None)


def _register(event, definition):
    entries, result = _results(event, definition)
    if event["final_result_id"] != result.result_id or event["round_ids"] != [r.round_id for r in entries]:
        raise ContractError("final_result_conflict")
    # registry→원장 순서. 등록 후 링크 저장 실패 사이 archive/delete도 참조를 본다.
    with model_registry.REGISTRY_LOCK:
        entry = training_model_service.register_completed_result(entries[-1].round_id)
        artifact = model_registry.get_ridge_artifact(entry)
        if (entry.name != definition["model_name"] or entry.version == definition["version"]
                or entry.metadata["result_id"] != result.result_id
                or list(artifact.parameters) != result.parameters
                or artifact.manifest["source_result"]["checksum"] != result.checksum):
            raise ContractError("registered_artifact_conflict")
        return events.update(event["event_id"], status="registered", error_code=None,
            registered_model={"name": entry.name, "version": entry.version, "artifact_id": artifact.artifact_id,
                "weights_sha256": artifact.weights_sha256, "manifest_sha256": artifact.manifest_sha256,
                "result_id": result.result_id, "round_id": result.round_id})


def advance(identity):
    event = events.get_event(identity)  # 어떤 외부 생성도 durable 상태를 다시 읽은 뒤 수행한다.
    definition = _config(event)
    handlers = {"cleaning_intent": _clean_intent, "wait_cleaning": _wait_clean,
                "training_intent": _train_intent, "training": _wait_training, "wait_registration": _register}
    try:
        if event["status"] == "queued":
            return events.update(identity, status="cleaning_intent", error_code=None)
        if event["status"] in handlers:
            return handlers[event["status"]](event, definition)
        return event
    except ContractError as exc:
        pending = event["status"] in ("training_intent", "training", "wait_registration") and exc.references_pending
        return events.update(identity, status="failed", resume_status=event["status"], error_code=str(exc), references_pending=pending)
    except (HTTPException, OSError, ValueError) as exc:
        # 실패 예외 본문에는 입력 값이 들어 있을 수 있어 고정 분류만 보존한다.
        return events.update(identity, error_code="HTTP_" + str(exc.status_code) if isinstance(exc, HTTPException)
                             else type(exc).__name__)
