"""이벤트/고정 child intent 원장. 외부 작업 생성은 실행 모듈에서 잠금 밖으로 수행한다."""
import threading
from datetime import datetime, timezone

from fastapi import HTTPException

from models.cleaning_schemas import CleaningJobCreate
from models.federated_schemas import TrainingJobRequest
from models.retraining_schemas import RetrainCommand
from services import distribution_service as ledger, model_registry
from silo_sdk.distributions import sha

_tick_lock = threading.RLock()


def stamp():
    return datetime.now(timezone.utc).isoformat()


def overview():
    with ledger._lock:
        state = ledger._load()
        configs = [dict(state["retrain_configs"][identity], error_code=state["retrain_errors"].get(identity, {}).get("code"))
                   for identity in state["retrain_config_current"].values()]
        events = sorted(state["retrain_events"].values(), key=lambda e: (e["created_at"], e["event_id"]), reverse=True)
        options = [dict(config_id=c["config_id"], model_name=c["model_name"], version=c["version"], feature=c["feature"],
                        policy_id=state["drift_policy_current"].get(c["config_id"])) for c in state["configs"].values()]
    from services import silo_group_service
    groups = [dict(group_id=g.group_id, members=len(g.member_node_ids)) for g in silo_group_service.list_groups()]
    return {"configs": configs, "events": events, "options": options, "groups": groups}


def get_event(identity):
    with ledger._lock:
        return ledger._required(ledger._load(), "retrain_events", identity)


def cleaning_reserved(job_id, generation):
    """정제 reschedule의 job lock 안에서 조회한다. 여기서는 외부 작업 I/O를 하지 않는다."""
    with ledger._lock:
        return any(e["cleaning_request"]["job_id"] == job_id and e["cleaning_generation"] == generation
                   and e["cleaning_snapshot"] is not None and e["status"] not in ("registered", "failed")
                   for e in ledger._load()["retrain_events"].values())


def reserve_registration(job_id, result_id, owner_event_id):
    """caller는 registry lock 보유. 모델 게시 전에 원장 참조를 원자적으로 예약한다."""
    # 소유권은 원장 밖의 영속 학습 잡에서 읽는다. 일반 등록은 원장을 열지 않는다.
    if owner_event_id is None:
        return
    with ledger._lock:
        state = ledger._load()
        event = ledger._required(state, "retrain_events", owner_event_id)
        request = event["training_request"]
        if request["job_id"] != job_id or request.get("retraining_event_id") != owner_event_id:
            raise HTTPException(409, "재교육 학습 잡의 소유 원장이 일치하지 않습니다")
        if result_id not in event["registration_result_ids"]:
            event["registration_result_ids"].append(result_id)
            ledger._save(state)


def update(identity, **values):
    with ledger._lock:
        state = ledger._load()
        event = ledger._required(state, "retrain_events", identity)
        event = dict(event, **values, updated_at=stamp())
        state["retrain_events"][identity] = event
        ledger._save(state)
        return event


def _requests(identity, definition):
    owner = "retrain:" + identity
    clean = CleaningJobCreate(job_id="rc-" + identity[:60], recipe_name=definition["recipe_name"],
        recipe_version=definition["recipe_version"], group_id=definition["group_id"],
        dataset_label=definition["dataset_label"], notes=owner, **definition["cleaning"])
    train = TrainingJobRequest(job_id="rt-" + identity[:60], model_name=definition["model_name"],
        version=definition["version"], group_id=definition["group_id"], schedule_kind="chain",
        max_rounds=definition["max_rounds"], min_contributions=len(definition["topology"]["roots"]),
        retraining_event_id=identity,
        notes=owner, cleaning_job_id=clean.job_id, learning=definition["live_learning"],
        worker_endpoints=definition["worker_endpoints"])
    return clean.model_dump(mode="json"), train.model_dump(mode="json")


def _create(command, automatic):
    identity = sha(["retrain-auto-v1", command.retrain_config_id, command.drift_event_id]) if automatic else sha(
        ["retrain-manual-v1", command.request_id])
    request_hash = sha(dict(command.model_dump(), automatic=automatic))
    with model_registry.REGISTRY_LOCK, ledger._lock:
        state = ledger._load()
        prior = state["retrain_events"].get(identity)
        if prior:
            if prior["request_hash"] != request_hash:
                raise HTTPException(409, "같은 재교육 명령 ID에 다른 요청입니다")
            return prior
        config = ledger._required(state, "retrain_configs", command.retrain_config_id)
        definition = config["definition"]
        if (not definition["enabled"] or state["retrain_config_current"].get(definition["config_id"])
                != command.retrain_config_id or automatic and not definition["auto_enabled"]):
            raise HTTPException(409, "현재 활성 재교육 설정을 선택하세요")
        model = model_registry.get_model(definition["model_name"], definition["version"])
        if model.status != "active":
            raise HTTPException(409, "활성 기준 모델이 아닙니다")
        artifact = model_registry.get_ridge_artifact(model)
        if artifact.manifest_sha256 != definition["manifest_sha256"]:
            raise HTTPException(409, "예약된 기준 artifact 무결성이 다릅니다")
        if command.drift_event_id:
            drift = ledger._required(state, "drift_events", command.drift_event_id)
            if (drift["config_id"] != definition["config_id"] or drift["policy"] is None
                    or drift["policy"]["policy_id"] != definition["policy_id"]):
                raise HTTPException(409, "재교육 설정과 분포 이벤트의 정책/범위가 다릅니다")
            if automatic and (drift["state"] != "ready" or drift["severity"] != "critical"
                    or state["drift_current"].get(sha([drift["config_id"], drift["node_id"]])) != drift["event_id"]):
                raise HTTPException(409, "자동 재교육은 현재 유효한 critical 이벤트만 허용합니다")
        elif automatic:
            raise HTTPException(422, "자동 재교육에는 실제 분포 이벤트가 필요합니다")
        clean, train = _requests(identity, definition)
        event = dict(event_id=identity, request_hash=request_hash, request_id=command.request_id,
            retrain_config_id=command.retrain_config_id, drift_event_id=command.drift_event_id,
            automatic=automatic, status="queued", created_at=stamp(), updated_at=stamp(),
            cleaning_request=clean, training_request=train, error_code=None, cleaning_snapshot=None, cleaning_generation=0,
            round_ids=[], final_result_id=None, registered_model=None, registration_result_ids=[], references_pending=True)
        state["retrain_events"][identity] = event
        ledger._save(state)  # 저장 실패 시 외부 작업 생성0. 같은 프로세스 재시도도 다시 원장을 읽는다.
        return event


def create_manual(body):
    return _create(RetrainCommand(**body), False)


def retry(identity):
    with _tick_lock, model_registry.REGISTRY_LOCK:
        event = get_event(identity)
        if event["status"] != "failed":
            raise HTTPException(409, "실패한 재교육 이벤트만 같은 child ID로 재확인할 수 있습니다")
        with ledger._lock:
            definition = ledger._required(ledger._load(), "retrain_configs", event["retrain_config_id"])["definition"]
        model = model_registry.get_model(definition["model_name"], definition["version"])
        if model.status != "active" or model_registry.get_ridge_artifact(model).manifest_sha256 != definition["manifest_sha256"]:
            raise HTTPException(409, "기준 모델/가중치를 복원한 후 같은 실행을 재확인하세요")
        return update(identity, status=event["resume_status"], error_code=None, references_pending=True)


def _enqueue_automatic():
    from services import distribution_drift
    distribution_drift.overview()  # 신선도도 재평가한 실제 현재 event만 소비한다.
    with ledger._lock:
        state = ledger._load()
        configs = [state["retrain_configs"][key] for key in state["retrain_config_current"].values()]
        events = [state["drift_events"][key] for key in state["drift_current"].values()]
    for config in configs:
        definition = config["definition"]
        if not definition["enabled"] or not definition["auto_enabled"]:
            continue
        for event in events:
            if (event["config_id"] == definition["config_id"] and event["state"] == "ready"
                    and event["severity"] == "critical" and event["policy"]["policy_id"] == definition["policy_id"]):
                try:
                    _create(RetrainCommand(retrain_config_id=config["retrain_config_id"],
                        request_id="auto:" + event["event_id"], drift_event_id=event["event_id"]), True)
                    _auto_error(config["retrain_config_id"], None)
                except (HTTPException, OSError, ValueError) as exc:
                    code = "HTTP_" + str(exc.status_code) if isinstance(exc, HTTPException) else type(exc).__name__
                    _auto_error(config["retrain_config_id"], code)


def _auto_error(identity, code):
    with ledger._lock:
        state = ledger._load()
        if code is None:
            if identity not in state["retrain_errors"]:
                return
            del state["retrain_errors"][identity]
        else:
            state["retrain_errors"][identity] = {"code": code, "at": stamp()}
        ledger._save(state)


def tick(limit=8):
    from services import retraining_execution
    with _tick_lock:
        try:
            _enqueue_automatic()
        except (HTTPException, OSError, ValueError):
            pass  # 원장/설정 오류가 이미 생성된 다른 실행의 복구를 막지 않는다.
        events = overview()["events"]
        pending = sorted((e for e in events if e["status"] not in ("registered", "failed")),
                         key=lambda e: (e["updated_at"], e["event_id"]))
        advanced = []
        for event in pending[:limit]:
            try:
                retraining_execution.advance(event["event_id"])
                advanced.append(event["event_id"])
            except (HTTPException, OSError, ValueError):
                # 저장 실패 후 메모리 상태를 재사용하지 않는다. 다음 tick은 원본 intent를 재조회한다.
                continue
        return advanced
