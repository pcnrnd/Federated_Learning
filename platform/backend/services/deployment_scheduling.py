"""같은 배포 저장소의 영속 schedule opening intent. 회차 게시/응답 유실은 같은 ID로 복구한다."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from services import deployment_service as service, model_registry

_tick_lock = threading.RLock()


def owned_run_ids(parent):
    """저장된 소유 회차와 legacy 복원 연결을 끝까지 확인한다. cycle은 정리 성공이 아니다."""
    entries = {entry.deployment_id: entry for entry in service.list_deployments()}
    seeds = {parent.current_run_id, parent.opening_run_id} - {None}
    seeds.update(entry.deployment_id for entry in entries.values() if entry.schedule_parent_id == parent.deployment_id)
    owned = set()
    for seed in seeds:
        identity, chain = seed, set()
        while identity:
            if identity in chain:
                raise HTTPException(status_code=409, detail="복원 실행 연결의 순환으로 정리를 확인할 수 없습니다")
            chain.add(identity)
            owned.add(identity)
            entry = entries.get(identity)
            if entry is None:  # 아직 게시되지 않은 opening/rollback intent.
                break
            if entry.is_schedule or entry.schedule_parent_id not in (None, parent.deployment_id):
                raise HTTPException(status_code=409, detail="복원 실행의 일정 소유권을 확인할 수 없습니다")
            identity = entry.rollback_run_id
    return owned


def owner_for(identity):
    """이전 버전이 parent 없이 게시한 복원도 저장된 chain으로만 소유권을 복구한다."""
    owners = [entry.deployment_id for entry in service.list_deployments()
              if entry.is_schedule and identity in owned_run_ids(entry)]
    if len(owners) > 1:
        raise HTTPException(status_code=409, detail="복원 실행의 일정 소유권이 중복됩니다")
    return owners[0] if owners else None


def _restored_tip(parent):
    owned_run_ids(parent)  # cycle/다른 일정 연결을 먼저 거부한다.
    current = service.get_deployment(parent.current_run_id)
    if (current.rollback_run_id and current.status != "rolled_back"
            and parent.status != "stopped" and not parent.cleanup_pending):
        try:
            target = service.get_deployment(current.rollback_run_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            target = None
        if target is None or target.status in ("pending", "running"):
            # parent를 물려받은 pending 복원은 일반 pending-loop 대신 같은 복원 명령으로 복구한다.
            return service.rollback_deployment(current.deployment_id)
    while current.status == "rolled_back" and current.rollback_run_id:
        current = service.get_deployment(current.rollback_run_id)
    return current


def _child(parent, identity):
    try:
        entry = service.get_deployment(identity)
        if entry.schedule_parent_id != parent.deployment_id or entry.occurrence != parent.occurrence + 1:
            raise HTTPException(status_code=409, detail="배포 회차 정체성 불일치")
        return entry
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    with model_registry.REGISTRY_LOCK:
        service._require_active(parent.configuration)
        child = parent.model_copy(deep=True, update={"deployment_id": identity, "is_schedule": False,
            "schedule_active": False, "schedule_parent_id": parent.deployment_id,
            "occurrence": parent.occurrence+1, "scheduled_at": parent.next_due_at, "next_due_at": None,
            "opening_run_id": None, "current_run_id": None, "status": "pending", "container_map": {},
            "target_results": {}, "verified_at": None, "launch_pending": True,
            "cleanup_pending": False, "cleanup_results": {}, "error": None,
            "created_at": service._now_iso(), "previous_deployment_id": parent.current_run_id or parent.previous_deployment_id})
        service._save(child)
        return child


def advance(parent):
    """호출자는 부모별 operation lock을 소유한다. 실패 회차는 자동으로 새 회차로 대체하지 않는다."""
    if parent.opening_run_id is None:
        parent = parent.model_copy(update={"opening_run_id": uuid.uuid4().hex})
        service._save(parent)  # child 생성 전 의도; 저장 실패면 실제 create0.
    child = _child(parent, parent.opening_run_id)
    if child.status == "pending":
        child = service.retry_deployment(child.deployment_id)
    elif child.status == "running":
        service.reconcile_deployment(child.deployment_id)
        child = service.get_deployment(child.deployment_id)
    if child.status != "running" or not child.verified_at:
        failed = parent.model_copy(update={"status": "failed", "schedule_active": False,
            "error": "해당 일괄 회차의 실제 기동/검증 실패. 같은 회차를 재시도하거나 정지하세요"})
        service._save(failed)
        return failed
    if parent.current_run_id and parent.current_run_id != child.deployment_id:
        old = service.stop_deployment(parent.current_run_id)
        if old.cleanup_pending or old.launch_pending or old.container_map:
            failed = parent.model_copy(update={"status": "failed", "schedule_active": False,
                "error": "새 회차는 검증됐으나 이전 회차 정리가 미확인입니다"})
            service._save(failed)
            return failed
    due = datetime.fromisoformat(parent.next_due_at)
    parent = parent.model_copy(update={"current_run_id": child.deployment_id, "opening_run_id": None,
        "occurrence": child.occurrence, "status": "pending", "schedule_active": True, "error": None,
        "next_due_at": (due+timedelta(seconds=parent.interval_seconds)).isoformat()})
    service._save(parent)
    return parent


def tick(now=None):
    now = now or datetime.now(timezone.utc)
    processed = []
    with _tick_lock:
        # scheduler 중단 시 남은 실제 pending 실행도 고정 ID/name/target 의도로 복구한다.
        for entry in service.list_deployments():
            if (not entry.is_schedule and entry.schedule_parent_id is None and entry.status == "pending"
                    and entry.configuration is not None):
                service.retry_deployment(entry.deployment_id)
        for snapshot in service.list_deployments():
            if not snapshot.is_schedule:
                continue
            with service._operation_lock(snapshot.deployment_id):
                fresh = service.get_deployment(snapshot.deployment_id)
                if not fresh.schedule_active and fresh.current_run_id:
                    current = _restored_tip(fresh)
                    if current.deployment_id != fresh.current_run_id:
                        fresh = fresh.model_copy(update={"current_run_id": current.deployment_id,
                            "opening_run_id": None, "error": "회차 복원 완료; 자동 일정 중지"})
                        service._save(fresh)
                if not fresh.schedule_active:
                    continue
                if fresh.opening_run_id or (fresh.next_due_at and datetime.fromisoformat(fresh.next_due_at) <= now):
                    advance(fresh)
                    processed.append(fresh.deployment_id)
    return processed


def retry_schedule(parent):
    if not parent.opening_run_id:
        raise HTTPException(status_code=409, detail="재시도할 실패 회차가 없습니다")
    child = _child(parent, parent.opening_run_id)
    if child.status == "failed":
        service.retry_deployment(child.deployment_id)
    return advance(parent)


def stop_schedule(parent):
    parent = parent.model_copy(update={"schedule_active": False, "cleanup_pending": True})
    service._save(parent)  # 다음 회차부터 먼저 금지; Docker I/O는 registry lock 밖.
    pending = False
    try:
        identities = owned_run_ids(parent)
    except HTTPException:
        failed = parent.model_copy(update={"status": "failed", "cleanup_pending": True,
            "error": "일괄 회차 복원 연결/소유권 정리가 미확인입니다"})
        service._save(failed)
        return failed
    for identity in identities:
        try:
            child = service.stop_deployment(identity)
        except HTTPException as exc:
            if exc.status_code == 404:
                continue  # child 게시 전 intent만 저장된 경우.
            pending = True  # route/진행 요청 pin 등 미확인 정리를 parent 성공으로 숨기지 않는다.
            continue
        pending = pending or child.cleanup_pending or child.launch_pending or bool(child.container_map)
    parent = parent.model_copy(update={"status": "failed" if pending else "stopped", "cleanup_pending": pending,
        "error": "일부 일괄 회차 정리가 미확인입니다" if pending else None})
    service._save(parent)
    return parent
