"""학습 라운드 + 파라미터 수집 서비스"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import HTTPException

from config.federated_manager import (
    get_training_round,
    load_round_contributions,
    load_training_rounds,
    upsert_contribution,
    upsert_training_round,
)
from models.federated_schemas import (
    AggregateResult,
    ParameterContribution,
    ParameterContributionRecord,
    TrainingRound,
    TrainingRoundCreate,
)
from services import fedavg_aggregator, silo_group_service
from services.model_registry import get_model
from silo_sdk import training_protocol as protocol

logger = logging.getLogger(__name__)

_round_lock = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_round(entry: TrainingRound) -> None:
    # 라운드 1건 upsert — 이력 전체 read-modify-write를 피한다 (SQLite: 단일 행, YAML: 파일 단위)
    with _round_lock:
        upsert_training_round(entry.round_id, entry.model_dump())


def list_rounds(
    *,
    model_name: str | None = None,
    group_id: str | None = None,
    status: str | None = None,
) -> list[TrainingRound]:
    with _round_lock:
        raw = load_training_rounds()
    rounds = [TrainingRound(**v) for v in raw.values()]
    if model_name:
        rounds = [r for r in rounds if r.model_name == model_name]
    if group_id:
        rounds = [r for r in rounds if r.group_id == group_id]
    if status:
        rounds = [r for r in rounds if r.status == status]
    rounds.sort(key=lambda r: r.created_at, reverse=True)
    return rounds


def get_round(round_id: str) -> TrainingRound:
    with _round_lock:
        raw = get_training_round(round_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="학습 라운드를 찾을 수 없습니다")
    return TrainingRound(**raw)


def create_round(request: TrainingRoundCreate, *, opening_id: str | None = None,
                 job_id: str | None = None, occurrence: int | None = None) -> TrainingRound:
    """고정 opening identity의 재시도는 기존 동결 라운드를 그대로 반환한다."""
    request_hash = hashlib.sha256(json.dumps(request.model_dump(mode="json"), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    with _round_lock:
        if opening_id:
            existing = get_training_round(opening_id)
            if existing is not None:
                entry = TrainingRound(**existing)
                if (entry.job_id != job_id or entry.job_occurrence != occurrence
                        or entry.opening_request_hash != request_hash):
                    raise HTTPException(status_code=409, detail="고정 회차와 기존 라운드의 생성 정체성 불일치")
                return entry
        return _create_round(request, opening_id=opening_id, job_id=job_id,
                             occurrence=occurrence, request_hash=request_hash)


def _create_round(request, *, opening_id, job_id, occurrence, request_hash) -> TrainingRound:
    """학습 라운드 생성 — 모델/그룹 존재 사전 검증"""
    get_model(request.model_name, request.version)
    group = silo_group_service.get_group(request.group_id)
    cleaned = None
    if request.cleaning_job_id:
        from services.cleaning_execution import require_training_output
        cleaned = require_training_output(request.cleaning_job_id)
    members = list(group.member_node_ids)
    # 집계자는 클러스터 1개만 맡는다 (silo_group_service 규칙) — 집계자 → 멤버 사본
    clusters = {
        g.aggregator_node_id: list(g.member_node_ids)
        for g in silo_group_service.list_groups()
        if g.aggregator_node_id in members
    }
    outputs = None if cleaned is None else {
        s.silo_id: {**s.model_dump(include={"output_id", "output_hash", "source_hash", "recipe_hash",
            "schema_fingerprint", "attempt_id", "rows_in", "rows_out"}),
            "generation": cleaned.generation, "recipe_name": cleaned.recipe_name,
            "recipe_version": cleaned.recipe_version} for s in cleaned.shards}
    required = set(members) | {child for children in clusters.values() for child in children}
    if outputs is not None and not required.issubset(outputs):
        raise HTTPException(status_code=409, detail="정제 출력이 학습 참여 스냅샷 전체를 포함하지 않습니다")

    live = {}
    if request.learning is not None:
        if outputs is None:
            raise HTTPException(status_code=422, detail="live 학습에는 성공 정제 출력이 필요합니다")
        if set(outputs) != required:
            raise HTTPException(status_code=409, detail="정제 출력과 현재 root/leaf 참여 스냅샷이 정확히 일치하지 않습니다")
        children = [child for group_members in clusters.values() for child in group_members]
        if len(set(children)) != len(children) or set(children) & set(members):
            raise HTTPException(status_code=422, detail="live 학습은 겹치지 않는 정확한 2단 계층만 지원합니다")
        if request.min_contributions > len(members):
            raise HTTPException(status_code=422, detail="정족수가 중앙 대표 참여자 수보다 큽니다")
        try:
            settings = request.learning.model_dump()
            space = protocol.space_checksum(request.model_name, request.version, settings,
                                            {node: outputs[node] for node in required})
            base = settings["initial_parameters"]
            if request.parent_round_id:
                parent = get_round(request.parent_round_id)
                if (parent.status != "completed" or not parent.result or parent.space_checksum != space
                        or parent.model_name != request.model_name or parent.version != request.version):
                    raise ValueError("직전 전역 결과와 현재 모델 공간/버전이 일치하지 않습니다")
                base = get_result(parent.round_id).parameters
            endpoints = request.worker_endpoints or {node: f"http://{node}:8081" for node in required}
            if set(endpoints) != required:
                raise ValueError("worker 주소는 전체 root/leaf 스냅샷과 일치해야 합니다")
            for endpoint in endpoints.values():
                parsed = urlparse(endpoint)
                if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
                        or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")
                        or parsed.port == 2375):
                    raise ValueError("worker HTTP 주소가 유효하지 않습니다(Docker API 주소 사용 불가)")
            base = protocol.vector(base, len(settings["features"]) + 1)
            live = {"learning": request.learning, "parent_round_id": request.parent_round_id,
                    "base_parameters": base, "base_checksum": protocol.parameter_checksum(base),
                    "space_checksum": space, "transport_snapshot": dict(endpoints)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    elif request.parent_round_id:
        raise HTTPException(status_code=422, detail="전역 피드백에는 live learning 계약이 필요합니다")

    entry = TrainingRound(
        round_id=opening_id or uuid.uuid4().hex,
        model_name=request.model_name,
        version=request.version,
        group_id=request.group_id,
        min_contributions=request.min_contributions,
        status="open",
        contributors=[],
        total_samples=0,
        created_at=_now_iso(),
        notes=request.notes,
        # open 시점 멤버를 동결 — 라운드 도중 그룹이 바뀌어도 진행 중 라운드는 무영향
        member_snapshot=members,
        cluster_snapshot=clusters,
        cleaning_job_id=request.cleaning_job_id,
        cleaning_snapshot=outputs,
        job_id=job_id,
        job_occurrence=occurrence,
        opening_request_hash=request_hash if opening_id else None,
        **live,
    )
    # 라운드 파일의 모든 쓰기는 _round_lock으로 직렬화한다 — 잠금 없이 쓰면
    # 동시 기여/집계의 load→save 와 read-modify-write 경합으로 방금 만든 라운드가
    # 유실된다 (실측: 250라운드 연속 실행 중 기여 404)
    with _round_lock:
        _save_round(entry)
    logger.info("학습 라운드 생성: %s (%s@%s, group=%s)",
                entry.round_id, request.model_name, request.version, request.group_id)
    return entry


def _verify_membership(round_entry: TrainingRound, silo_id: str) -> None:
    """라운드 open 시점의 멤버 스냅샷과 대조한다 (HFL 설계 스펙 §4.2).

    스냅샷이 `None`이면 스냅샷 도입 이전에 생성된 레코드이므로 현재 그룹 멤버십으로
    폴백한다 — 진행 중이던 기존 라운드의 하위 호환.
    빈 목록 `[]`은 "멤버 0명인 그룹의 스냅샷"이라는 유효한 상태이므로 폴백하지 않는다
    (폴백하면 라운드 도중 추가된 노드가 기여할 수 있어 스냅샷 규칙이 무효가 된다).
    """
    allowed = round_entry.member_snapshot
    if allowed is None:
        allowed = silo_group_service.get_group(round_entry.group_id).member_node_ids
    if silo_id not in allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                f"사일로 '{silo_id}'는 라운드 '{round_entry.round_id}'의 "
                f"참여 스냅샷(그룹 '{round_entry.group_id}')에 없습니다"
            ),
        )


def _verify_aggregated_from(
    round_entry: TrainingRound, silo_id: str, aggregated_from: list[str],
) -> None:
    """대리 제출 출처 검증 (HFL 설계 스펙 §4.2).

    ① 제출자가 해당 클러스터의 집계자인가 → 아니면 403
    ② 하위 목록에 중복이 없는가 → 있으면 422 (리니지 정확도)
    ③ 하위 목록이 클러스터 멤버의 부분집합인가 → 아니면 422
       (집계자는 자기 클러스터의 멤버가 될 수 없으므로 자기 자신 포함도 여기서 422)
    """
    if not aggregated_from:
        return  # 평면 제출 — 기존 경로와 완전히 동일

    if round_entry.cluster_snapshot is None:
        # 도입 이전 레코드만 현재 그룹으로 추정한다. 빈 스냅샷은 폴백하지 않는다.
        cluster = silo_group_service.get_cluster_by_aggregator(silo_id)
        allowed = cluster.member_node_ids if cluster is not None else None
    else:
        allowed = round_entry.cluster_snapshot.get(silo_id)
    if allowed is None:
        raise HTTPException(
            status_code=403,
            detail=f"사일로 '{silo_id}'는 라운드의 클러스터 집계자가 아니므로 대리 제출할 수 없습니다",
        )

    duplicated = sorted({n for n in aggregated_from if aggregated_from.count(n) > 1})
    if duplicated:
        raise HTTPException(
            status_code=422,
            detail=f"aggregated_from에 중복된 하위 노드: {duplicated}",
        )

    outside = [n for n in aggregated_from if n not in allowed]
    if outside:
        raise HTTPException(
            status_code=422,
            detail=f"라운드 '{round_entry.round_id}'의 클러스터 멤버가 아닌 하위 노드: {outside}",
        )


def _checksum_params(parameters: list[float]) -> str:
    raw = ",".join(f"{v:.10g}" for v in parameters).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _record_response(round_id, record):
    return ParameterContributionRecord(round_id=round_id,
        parameter_dim=len(record["parameters"]), **{k: v for k, v in record.items()
            if k in ParameterContributionRecord.model_fields and k not in ("round_id", "parameter_dim")})


def _reconcile_statistics(entry, bucket):
    """원장 저장 뒤 통계 게시 전 장애는 원장을 유일한 기준으로 복구한다."""
    changed = entry.model_copy(update={"contributors": list(bucket),
        "total_samples": sum(r["sample_count"] for r in bucket.values()),
        "cleaning_stats": {node: {key: record[key] for key in
            ("rows_before_cleaning", "rows_after_cleaning", "train_rmse") if record.get(key) is not None}
            for node, record in bucket.items() if any(record.get(key) is not None for key in
                ("rows_before_cleaning", "rows_after_cleaning", "train_rmse"))}})
    if changed != entry:
        _save_round(changed)
    return changed


def submit_contribution(contribution: ParameterContribution) -> ParameterContributionRecord:
    """사일로의 파라미터 기여를 라운드에 등록한다."""
    with _round_lock:
        entry = get_round(contribution.round_id)
        round_bucket = load_round_contributions(contribution.round_id)
        live_fields = {}
        if entry.learning is not None:
            try:
                normalized = protocol.validate_envelope(entry.model_dump(), contribution.model_dump())
            except (ValueError, KeyError, TypeError) as exc:
                raise HTTPException(status_code=422, detail="live 원기여/표본/모델 공간 검증 실패") from exc
            previous = round_bucket.get(contribution.silo_id)
            if previous is not None:
                if previous.get("envelope_checksum") != normalized["envelope_checksum"]:
                    raise HTTPException(status_code=409, detail="같은 대표의 다른 원기여는 덮어쓸 수 없습니다")
                if entry.status in ("open", "aggregating"):
                    _reconcile_statistics(entry, round_bucket)
                return _record_response(entry.round_id, previous)
            seen = {leaf["silo_id"] for record in round_bucket.values() for leaf in record.get("origins", [])}
            if seen & {leaf["silo_id"] for leaf in normalized["origins"]}:
                raise HTTPException(status_code=409, detail="겹친 원기여를 두 번 합산할 수 없습니다")
            live_fields = {key: normalized[key] for key in
                           ("base_checksum", "space_checksum", "envelope_checksum", "origins")}
        if entry.status != "open":
            raise HTTPException(
                status_code=409,
                detail=f"라운드 상태가 '{entry.status}'이므로 기여를 받을 수 없습니다",
            )
        _verify_membership(entry, contribution.silo_id)
        _verify_aggregated_from(entry, contribution.silo_id, contribution.aggregated_from)

        if contribution.silo_id in round_bucket:
            raise HTTPException(
                status_code=409,
                detail=f"사일로 '{contribution.silo_id}'는 이미 기여하였습니다",
            )

        record = {
            "silo_id": contribution.silo_id,
            "sample_count": contribution.sample_count,
            "parameters": list(contribution.parameters),
            "submitted_at": _now_iso(),
            "checksum": contribution.checksum or _checksum_params(contribution.parameters),
            "aggregated_from": list(contribution.aggregated_from),
            **contribution.cleaning_stats(),
            **live_fields,
        }
        if entry.learning is not None:
            leaves = live_fields["origins"]
            local_sse = sum(leaf["sample_count"] * max(0.0, 2 * leaf["objective"]
                - entry.learning.l2 * sum(w*w for w in leaf["parameters"][:-1])) for leaf in leaves)
            record.update({"rows_before_cleaning": sum(entry.cleaning_snapshot[leaf["silo_id"]]["rows_in"] for leaf in leaves),
                "rows_after_cleaning": sum(leaf["rows_seen"] for leaf in leaves),
                "train_rmse": math.sqrt(local_sse / contribution.sample_count)})
        upsert_contribution(contribution.round_id, contribution.silo_id, record)

        _reconcile_statistics(entry, {**round_bucket, contribution.silo_id: record})

    logger.info(
        "기여 등록: round=%s silo=%s samples=%d dim=%d aggregated_from=%d",
        contribution.round_id,
        contribution.silo_id,
        contribution.sample_count,
        len(contribution.parameters),
        len(contribution.aggregated_from),
    )
    return _record_response(contribution.round_id, record)


def list_contributions(round_id: str) -> list[ParameterContributionRecord]:
    with _round_lock:
        contributions = load_round_contributions(round_id)
    records = [_record_response(round_id, r) for r in contributions.values()]
    records.sort(key=lambda r: r.submitted_at)
    return records


def aggregate_round(round_id: str) -> AggregateResult:
    """라운드의 기여들을 FedAvg로 집계해 글로벌 파라미터를 산출한다."""
    with _round_lock:
        entry = get_round(round_id)
        if entry.status == "completed":
            if entry.learning is not None and entry.result:
                return get_result(round_id)
            raise HTTPException(status_code=409, detail="이미 집계 완료된 라운드입니다")
        if entry.learning is not None and entry.status == "failed":
            raise HTTPException(status_code=409, detail="실패한 live 라운드를 집계 완료로 바꿀 수 없습니다")
        contributions = load_round_contributions(round_id)
        if len(contributions) < entry.min_contributions:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"기여수 부족: 현재 {len(contributions)} < "
                    f"min_contributions {entry.min_contributions}"
                ),
            )

        entry = _reconcile_statistics(entry, contributions)
        _save_round(entry.model_copy(update={"status": "aggregating"}))

        try:
            if entry.learning is not None:
                used = set()
                for record in contributions.values():
                    protocol.validate_envelope(entry.model_dump(), {"round_id": round_id, **record})
                    origins = {leaf["silo_id"] for leaf in record["origins"]}
                    if used & origins:
                        raise ValueError("중복 원기여가 원장에 있습니다")
                    used |= origins
            payload = [
                (r["silo_id"], r["sample_count"], r["parameters"])
                for r in contributions.values()
            ]
            aggregated, total = fedavg_aggregator.aggregate(payload)
            protocol.vector(aggregated)
        except ValueError as exc:
            _save_round(entry.model_copy(update={"status": "failed", "error": str(exc)}))
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        completed_at = _now_iso()
        checksum = protocol.parameter_checksum(aggregated)
        origins = [leaf for record in contributions.values() for leaf in record.get("origins", [])]
        result = AggregateResult(round_id=round_id, parameter_dim=len(aggregated), parameters=aggregated,
            total_samples=total, contributor_count=len(contributions), aggregated_at=completed_at,
            result_id=protocol.digest({"round_id": round_id, "checksum": checksum, "samples": total,
                                       "origins": sorted(leaf["contribution_id"] for leaf in origins)}),
            checksum=checksum, format="ridge-v1" if entry.learning else "parameters-v1",
            model_name=entry.model_name, version=entry.version,
            features=entry.learning.features if entry.learning else None,
            target=entry.learning.target if entry.learning else None,
            learning=entry.learning.model_dump() if entry.learning else None,
            base_checksum=entry.base_checksum, space_checksum=entry.space_checksum, origins=origins or None)
        completed = entry.model_copy(
            update={
                "status": "completed",
                "aggregated_parameter_dim": len(aggregated),
                "aggregated_at": completed_at,
                "total_samples": total,
                "result": result.model_dump(),
            }
        )
        _save_round(completed)

    logger.info(
        "라운드 집계 완료: %s dim=%d contributors=%d total_samples=%d",
        round_id,
        len(aggregated),
        len(contributions),
        total,
    )
    return result


def get_result(round_id: str) -> AggregateResult:
    entry = get_round(round_id)
    if entry.status != "completed" or entry.result is None:
        raise HTTPException(status_code=409, detail="영속 준비된 학습 결과가 없습니다")
    result = AggregateResult(**entry.result)
    if (result.parameter_dim != len(result.parameters)
            or protocol.parameter_checksum(result.parameters) != result.checksum):
        raise HTTPException(status_code=409, detail="영속 결과 무결성 검사 실패")
    return result


def report_execution_failure(round_id, failure):
    with _round_lock:
        entry = get_round(round_id)
        if entry.learning is None or failure.silo_id not in protocol.participants(entry.model_dump()):
            raise HTTPException(status_code=403, detail="live 참여 스냅샷에 없는 오류 보고")
        if entry.status == "completed":
            raise HTTPException(status_code=409, detail="완료 결과를 실패로 덮어쓸 수 없습니다")
        errors = dict(entry.execution_errors)
        errors.setdefault(failure.silo_id, {"error_code": failure.error_code, "at": _now_iso()})
        failed = entry.model_copy(update={"status": "failed", "execution_errors": errors,
            "error": f"{failure.silo_id}: {errors[failure.silo_id]['error_code']}"})
        if failed != entry:
            _save_round(failed)
        return failed
