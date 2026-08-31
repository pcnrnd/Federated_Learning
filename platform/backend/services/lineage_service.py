"""모델 lineage 서비스 — 버전 간 부모/자식 관계 + 변경 기록"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from config.maintenance_manager import load_lineage, save_lineage
from models.maintenance_schemas import (
    LineageNode,
    ModelLineage,
    ModelLineageRequest,
)
from services.model_registry import get_model, list_versions

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(model_name: str, version: str) -> str:
    return f"{model_name}::{version}"


def set_lineage(
    model_name: str, version: str, request: ModelLineageRequest
) -> ModelLineage:
    # 본 버전이 레지스트리에 있어야 한다
    get_model(model_name, version)
    # parent_version도 있어야 한다 (선언 시)
    if request.parent_version is not None:
        get_model(model_name, request.parent_version)

    lineage = load_lineage()
    entry = ModelLineage(
        model_name=model_name,
        version=version,
        parent_version=request.parent_version,
        change_type=request.change_type,
        change_notes=request.change_notes,
        derived_from_round_id=request.derived_from_round_id,
        recorded_at=_now_iso(),
    )
    lineage[_key(model_name, version)] = entry.model_dump()
    save_lineage(lineage)
    logger.info(
        "lineage 등록: %s@%s ← %s (%s)",
        model_name,
        version,
        request.parent_version,
        request.change_type,
    )
    return entry


def get_lineage(model_name: str, version: str) -> ModelLineage:
    lineage = load_lineage()
    key = _key(model_name, version)
    if key not in lineage:
        raise HTTPException(
            status_code=404, detail=f"lineage 미등록: {model_name}@{version}"
        )
    return ModelLineage(**lineage[key])


def list_for_model(model_name: str) -> list[ModelLineage]:
    lineage = load_lineage()
    items = [
        ModelLineage(**v) for v in lineage.values() if v.get("model_name") == model_name
    ]
    items.sort(key=lambda e: tuple(int(p) for p in e.version.split(".")))
    return items


def lineage_tree(model_name: str) -> list[LineageNode]:
    """루트(부모 없는 버전들)에서 시작하는 lineage 트리"""
    # 레지스트리 + lineage 합쳐서 노드 구성
    registry_versions = {v.version for v in list_versions(model_name)}
    recorded = {e.version: e for e in list_for_model(model_name)}
    # 미등록 버전은 부모 미정 상태로 노드 추가 (트리 일관성)
    all_versions = registry_versions | set(recorded.keys())

    nodes: dict[str, LineageNode] = {}
    for v in all_versions:
        meta = recorded.get(v)
        nodes[v] = LineageNode(
            version=v,
            parent_version=meta.parent_version if meta else None,
            change_type=meta.change_type if meta else "patch",
            change_notes=meta.change_notes if meta else "",
            children=[],
        )

    roots: list[LineageNode] = []
    for v, node in nodes.items():
        parent = node.parent_version
        if parent is not None and parent in nodes:
            nodes[parent].children.append(node)
        else:
            roots.append(node)

    def _sort_recursive(node: LineageNode) -> None:
        node.children.sort(key=lambda n: tuple(int(p) for p in n.version.split(".")))
        for child in node.children:
            _sort_recursive(child)

    for r in roots:
        _sort_recursive(r)
    roots.sort(key=lambda n: tuple(int(p) for p in n.version.split(".")))
    return roots


def ancestors(model_name: str, version: str) -> list[ModelLineage]:
    """루트까지의 조상 체인 (가까운 부모 → 루트 순).

    부모 버전에 lineage 기록이 없으면 기본값으로 합성 엔트리를 만들어 체인에 포함한다.
    """
    chain: list[ModelLineage] = []
    current_version = version
    lineage = load_lineage()
    visited: set[str] = set()
    while True:
        key = _key(model_name, current_version)
        if key not in lineage or current_version in visited:
            break
        visited.add(current_version)
        entry = ModelLineage(**lineage[key])
        if entry.parent_version is None:
            break
        parent_key = _key(model_name, entry.parent_version)
        if parent_key in lineage:
            chain.append(ModelLineage(**lineage[parent_key]))
        else:
            chain.append(
                ModelLineage(
                    model_name=model_name,
                    version=entry.parent_version,
                    parent_version=None,
                    change_type="patch",
                    change_notes="",
                    derived_from_round_id=None,
                    recorded_at="",
                )
            )
            break
        current_version = entry.parent_version
    return chain
