"""실제 요청의 primary/shadow HTTP 전송. 입력·예측은 요청 수명 밖에 보관하지 않는다."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import math
import time
import uuid

from fastapi import HTTPException

from models.serving_schemas import RoleObservation, RoleSummary, ServingComparison, ServingEvent, ServingRoute
from services import deployment_runtime, deployment_service, serving_store as store
from services.model_registry import REGISTRY_LOCK


def deployment(identity):
    entry = deployment_service.get_deployment(identity)
    if (entry.is_schedule or entry.status != "running" or not entry.verified_at or entry.launch_pending
            or entry.cleanup_pending or not entry.expected_image_id or not entry.expected_identity):
        raise HTTPException(status_code=409, detail="실제 기동·예측 검증된 실행이 필요합니다")
    if (set(entry.target_results) != set(entry.target_node_ids) or any(value.status != "running"
            or value.image_id != entry.expected_image_id or not value.endpoint for value in entry.target_results.values())):
        raise HTTPException(status_code=409, detail="모든 대상의 실측 endpoint/이미지 확인이 필요합니다")
    return entry


def _role(entry, inputs, identity):
    try:
        entry = deployment(entry.deployment_id)
    except HTTPException:
        return RoleObservation(deployment_id=entry.deployment_id, model_name=entry.model_name, version=entry.version,
            image_id=entry.expected_image_id, status="error", error_code="UnhealthyDeployment"), None
    nodes = sorted(entry.target_results)
    node = nodes[int(hashlib.sha256(identity.encode()).hexdigest(), 16) % len(nodes)]
    target = entry.target_results[node]
    start = time.perf_counter_ns()
    values = None
    error = None
    echoed = False
    try:
        value = deployment_runtime._json_request(target.endpoint + "/predict", {"inputs": inputs, "request_id": identity})
        if value.get("ok") is not True or value.get("input_count") != len(inputs):
            raise ValueError("InvalidResponse")
        if any(value.get(key) != expected for key, expected in entry.expected_identity.items()):
            raise ValueError("InvalidIdentity")
        if value.get("request_id") is not None and value["request_id"] != identity:
            raise ValueError("InvalidRequestIdentity")
        echoed = value.get("request_id") == identity
        values = value.get("predictions")
        valid_count = isinstance(values, list) and len(values) == len(inputs)
        if not valid_count:
            raise ValueError("InvalidOutputCount")
        deployment_runtime._finite_predictions(values)
    except Exception as exc:  # 네트워크/모델 오류의 입력·응답·예외 문자열은 저장하지 않는다.
        values = None
        error = "HTTP_"+str(exc.code) if hasattr(exc, "code") and isinstance(exc.code, int) else type(exc).__name__
    duration = (time.perf_counter_ns()-start)/1_000_000
    return RoleObservation(deployment_id=entry.deployment_id, model_name=entry.model_name, version=entry.version,
        node_id=node, image_id=entry.expected_image_id, status="ok" if error is None else "error",
        duration_ms=duration, error_code=error, request_id_echoed=echoed), values


def _differences(first, second):
    if isinstance(first, list) and isinstance(second, list) and len(first) == len(second) and first:
        result = []
        for a, b in zip(first, second):
            result.extend(_differences(a, b))
        return result
    if (isinstance(first, bool) or isinstance(second, bool) or not isinstance(first, (int, float))
            or not isinstance(second, (int, float))):
        raise ValueError("OutputShapeMismatch")
    value = abs(first-second)
    if not math.isfinite(value):
        raise ValueError("NonfiniteDifference")
    return [value]


def predict(route_id, request):
    identity = request.request_id or uuid.uuid4().hex
    with REGISTRY_LOCK:
        data = store.load()
        raw = data["routes"].get(route_id)
        if raw is None or raw["status"] == "closed":
            raise HTTPException(status_code=404, detail="활성 serving route가 없습니다")
        route = ServingRoute(**raw)
        if identity in data["requests"]:
            raise HTTPException(status_code=409, detail="이미 사용한 요청 ID입니다. 입력/예측은 보관하지 않아 재생하지 않습니다")
        primary = deployment_service.get_deployment(route.primary_deployment_id)
        sampled = int(hashlib.sha256(identity.encode()).hexdigest()[:8], 16) / 2**32 * 100 < route.mirror_pct
        shadow = deployment_service.get_deployment(route.shadow_deployment_id) if route.shadow_deployment_id and sampled else None
        event = ServingEvent(request_id=identity, route_id=route_id, generation=route.generation,
            owner_epoch=store.PROCESS_EPOCH, started_at=store.now(), input_count=len(request.inputs),
            primary_deployment_id=primary.deployment_id, shadow_deployment_id=shadow.deployment_id if shadow else None)
        data["requests"][identity] = event.model_dump()
        store.save(data)  # 실패하면 전송0. 진행 요청의 deployment 참조도 같은 파일에 예약한다.
    if shadow:
        with ThreadPoolExecutor(max_workers=2) as pool:
            primary_future = pool.submit(_role, primary, request.inputs, identity)
            shadow_future = pool.submit(_role, shadow, request.inputs, identity)
            primary_result, primary_values = primary_future.result()
            shadow_result, shadow_values = shadow_future.result()
        event.roles = {"primary": primary_result, "shadow": shadow_result}
        if primary_values is not None and shadow_values is not None:
            try:
                values = _differences(primary_values, shadow_values)
                event.mean_abs_difference = math.fsum(value/len(values) for value in values)
                if not math.isfinite(event.mean_abs_difference):
                    raise ValueError("NonfiniteDifference")
                event.difference_count = len(values)
                event.paired = True
            except (ValueError, OverflowError):
                event.mean_abs_difference = None
                event.comparison_error = "OutputComparisonInvalid"
    else:
        primary_result, primary_values = _role(primary, request.inputs, identity)
        event.roles = {"primary": primary_result}
    event.status, event.completed_at = "completed", store.now()
    with REGISTRY_LOCK:
        data = store.load()
        data["requests"][identity] = event.model_dump()
        store.save(data)  # 응답 게시 전 메타 저장. 실패/재시작은 pending→interrupted로 정직하게 남는다.
    if primary_values is None:
        raise HTTPException(status_code=502, detail=f"실제 primary 예측 실패 (request_id={identity})")
    return dict(route_id=route_id, generation=route.generation, request_id=identity,
        deployment_id=primary.deployment_id, predictions=primary_values, input_count=len(request.inputs),
        shadow_status=event.roles["shadow"].status if shadow else "not_sampled", **primary.expected_identity)


def comparison(route_id, *, at=None, data=None):
    data = data if data is not None else store.read()
    if route_id not in data["routes"]:
        raise HTTPException(status_code=404, detail="serving route가 없습니다")
    route = ServingRoute(**data["routes"][route_id])
    end = at or datetime.now(timezone.utc)
    seconds = route.comparison_gate.window_seconds if route.comparison_gate else 60
    start = end-timedelta(seconds=seconds)
    if route.comparison_started_at:
        start = max(start, datetime.fromisoformat(route.comparison_started_at))
    events = [ServingEvent(**value) for value in data["requests"].values() if value["route_id"] == route_id
        and value["generation"] == route.generation and start <= datetime.fromisoformat(value["started_at"]) <= end]
    roles = {}
    span = (end-start).total_seconds()
    for role in ("primary", "shadow"):
        assigned = [event for event in events if role == "primary" or event.shadow_deployment_id]
        observations = [event.roles[role] for event in assigned if role in event.roles]
        measured = [value.duration_ms for value in observations if value.duration_ms is not None]
        successes = sum(value.status == "ok" for value in observations)
        errors = sum(value.status == "error" for value in observations)
        roles[role] = RoleSummary(requests=len(assigned), successes=successes, errors=errors,
            interrupted=sum(event.status == "interrupted" for event in assigned), measured_requests=len(measured),
            mean_latency_ms=math.fsum(value/len(measured) for value in measured) if measured else None,
            throughput_rps=(successes+errors)/span if span > 0 else None)
    pairs = [event for event in events if event.paired and event.mean_abs_difference is not None]
    paired_roles = {}
    for role in ("primary", "shadow"):
        durations = [event.roles[role].duration_ms for event in pairs]
        paired_roles[role] = RoleSummary(requests=len(pairs), successes=len(pairs), measured_requests=len(durations),
            mean_latency_ms=math.fsum(value/len(durations) for value in durations) if durations else None,
            throughput_rps=len(pairs)/span if span > 0 else None)
    count = sum(event.difference_count for event in pairs)
    difference = math.fsum(event.mean_abs_difference*(event.difference_count/count) for event in pairs) if count else None
    latest = max((event.completed_at for event in pairs), default=None)
    reasons = _gate_reasons(route, events, pairs, difference, latest, roles, paired_roles, end)
    return ServingComparison(route_id=route_id, generation=route.generation, window_start=start.isoformat(),
        window_end=end.isoformat(), window_seconds=seconds, request_count=len(events),
        pending=sum(event.status == "pending" for event in events), interrupted=sum(event.status == "interrupted" for event in events),
        pairs=len(pairs), difference_count=count, mean_abs_difference=difference, latest_pair_at=latest,
        roles=roles, paired_roles=paired_roles, gate_ready=not reasons, gate_reasons=reasons, gate=route.comparison_gate)


def _gate_reasons(route, events, pairs, difference, latest, roles, paired_roles, end):
    gate = route.comparison_gate
    if not gate:
        return ["명시적인 비교 gate가 없습니다"]
    reasons = []
    if not route.shadow_deployment_id or route.status != "active":
        reasons.append("활성 shadow 비교 경로가 없습니다")
    if len(pairs) < gate.min_pairs:
        reasons.append("같은 요청의 유효 비교 N이 부족합니다")
    if latest is None or (end-datetime.fromisoformat(latest)).total_seconds() > gate.max_age_seconds:
        reasons.append("최근 유효 비교가 없습니다")
    if difference is None or difference > gate.max_mean_abs_difference:
        reasons.append("실제 예측 차이 기준을 충족하지 않습니다")
    if any(event.status != "completed" or event.comparison_error for event in events):
        reasons.append("진행/중단 또는 비교 형식 오류가 있습니다")
    for role, value in roles.items():
        if not value.requests or value.errors/value.requests > gate.max_error_rate:
            reasons.append(role+" 실제 오류율 기준을 충족하지 않습니다")
    if gate.max_latency_ratio is not None:
        primary, shadow = paired_roles["primary"].mean_latency_ms, paired_roles["shadow"].mean_latency_ms
        if primary is None or primary <= 0 or shadow is None or shadow/primary > gate.max_latency_ratio:
            reasons.append("실측 지연 비율 기준을 충족하지 않습니다")
    return reasons
