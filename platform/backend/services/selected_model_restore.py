"""레지스트리의 선택 name/version을 정확히 복원한다. 그 행의 previous로 이동하지 않는다."""
from contextlib import ExitStack
import uuid

from fastapi import HTTPException

from services import deployment_service as deployments, model_registry, serving_store


def restore(request):
    identity = uuid.uuid5(uuid.NAMESPACE_URL, "model-restore\0"+request.name+"\0"+request.version+"\0"+request.request_id).hex
    with deployments._operation_lock("model-restore-"+request.name), ExitStack() as stack:
        try:
            restored = deployments.get_deployment(identity)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            restored = None
        if restored is not None:
            if restored.restore_identity != request.model_dump():
                raise HTTPException(status_code=409, detail="선택 모델 복원 ID와 설정이 다릅니다")
            current_id = restored.restore_current_deployment_id
            current = deployments.get_deployment(current_id) if current_id else None
        else:
            candidates = [entry for entry in deployments.list_deployments() if entry.model_name == request.name
                and entry.version == request.version and entry.verified_at and entry.configuration and entry.expected_image_id]
            if not candidates:
                raise HTTPException(status_code=409, detail="선택 버전의 이전 실제 검증 설정이 없습니다")
            source = max(candidates, key=lambda entry: entry.created_at)
            current = deployments._latest_active_for(request.name)
        if current and current.schedule_parent_id:
            stack.enter_context(deployments._operation_lock(current.schedule_parent_id))
        if current:
            stack.enter_context(deployments._operation_lock(current.deployment_id))
            if serving_store.references(current.deployment_id):
                raise HTTPException(status_code=409, detail="실제 serving route의 복원은 해당 route에서 수행하세요")
        with model_registry.REGISTRY_LOCK:
            if restored is None:
                model_registry.restore_archived_model(request.name, request.version)
                restored = deployments._restore_entry(source, identity, extra={"restore_identity": request.model_dump(),
                    "restore_current_deployment_id": current.deployment_id if current else None,
                    "previous_deployment_id": current.deployment_id if current else source.deployment_id})
            if current and current.schedule_parent_id:
                parent = deployments.get_deployment(current.schedule_parent_id)
                if parent.opening_run_id or parent.current_run_id not in (current.deployment_id, restored.deployment_id):
                    raise HTTPException(status_code=409, detail="다음 batch 회차와 충돌하는 모델 복원입니다")
                deployments._save(parent.model_copy(update={"schedule_active": False}))
            if current:
                current = deployments.get_deployment(current.deployment_id)
                deployments._save(current.model_copy(update={"rollback_run_id": restored.deployment_id}))
        restored = deployments.retry_deployment(identity)
        if restored.status != "running" or not restored.verified_at:
            raise HTTPException(status_code=409, detail="선택 버전의 실제 복원 검증 실패")
        if current and current.deployment_id != restored.deployment_id:
            stopped = deployments.stop_deployment(current.deployment_id)
            if stopped.container_map or stopped.launch_pending or stopped.cleanup_pending:
                raise HTTPException(status_code=409, detail="선택 버전은 복원됐으나 이전 실행 정리가 미확인입니다")
            deployments._save(stopped.model_copy(update={"status": "rolled_back", "rollback_run_id": identity}))
            if current.schedule_parent_id:
                parent = deployments.get_deployment(current.schedule_parent_id)
                deployments._save(parent.model_copy(update={"current_run_id": identity, "opening_run_id": None,
                    "schedule_active": False, "status": "pending", "error": "선택 모델 복원 완료; 자동 일정 중지"}))
        return restored
