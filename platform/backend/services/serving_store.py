"""route 전환과 요청 메타를 한 파일에 원자 게시한다. raw 입력/예측/타깃은 받지 않는다."""
from copy import deepcopy
from datetime import datetime, timezone
import uuid
import yaml
from fastapi import HTTPException

from config import settings
from config.yaml_store import save_yaml_atomic
from services.model_registry import REGISTRY_LOCK

PROCESS_EPOCH = uuid.uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat()


def _path():
    return settings.CONFIG_DIR / "serving_routes.yaml"


def load():
    path = _path()
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise HTTPException(status_code=503, detail="serving 원장을 읽을 수 없습니다") from exc
        if not isinstance(data, dict) or not isinstance(data.get("routes"), dict) or not isinstance(data.get("requests"), dict):
            raise HTTPException(status_code=503, detail="serving 원장 형식이 유효하지 않습니다")
    else:
        data = {}
    data.setdefault("routes", {})
    data.setdefault("requests", {})
    data.setdefault("shadows", {})
    changed = False
    for event in data["requests"].values():
        if event["status"] == "pending" and event["owner_epoch"] != PROCESS_EPOCH:
            # 입력을 보관하지 않으므로 재실행하지 않는다. 측정값0/성공으로 복구하지 않는다.
            event.update(status="interrupted", completed_at=now(), comparison_error="ServerRestart")
            changed = True
    if changed:
        save(data)
    return data


def save(data):
    save_yaml_atomic(_path(), data)


def read():
    with REGISTRY_LOCK:
        return deepcopy(load())


def references(deployment_id):
    with REGISTRY_LOCK:
        data = load()
        for route in data["routes"].values():
            if route["status"] != "closed" and deployment_id in (
                    route["primary_deployment_id"], route.get("shadow_deployment_id"), route.get("previous_deployment_id")):
                return True
        return any(event["status"] == "pending" and deployment_id in
                   (event["primary_deployment_id"], event.get("shadow_deployment_id"))
                   for event in data["requests"].values())
