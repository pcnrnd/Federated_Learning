"""정제 레시피 서비스 — SemVer 기반 등록/조회"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from config.cleaning_manager import load_recipes, save_recipes
from models.cleaning_schemas import CleaningRecipe, CleaningRecipeRequest
from services.cleaning_recipes import validate_step_params

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _semver_tuple(version: str) -> tuple[int, int, int]:
    a, b, c = version.split(".")
    return int(a), int(b), int(c)


def list_recipes() -> list[CleaningRecipe]:
    raw = load_recipes()
    out: list[CleaningRecipe] = []
    for name, versions in raw.items():
        if not isinstance(versions, dict):
            continue
        for version, payload in versions.items():
            out.append(CleaningRecipe(name=name, version=version, **payload))
    out.sort(key=lambda r: (r.name, _semver_tuple(r.version)))
    return out


def get_recipe(name: str, version: str) -> CleaningRecipe:
    raw = load_recipes()
    if name not in raw or version not in raw[name]:
        raise HTTPException(
            status_code=404,
            detail=f"레시피 '{name}@{version}' 없음",
        )
    return CleaningRecipe(name=name, version=version, **raw[name][version])


def register_recipe(request: CleaningRecipeRequest) -> CleaningRecipe:
    # step 파라미터 사전 검증
    for step in request.steps:
        try:
            validate_step_params(step.type, step.params)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw = load_recipes()
    versions = raw.setdefault(request.name, {})
    if request.version in versions:
        raise HTTPException(
            status_code=409,
            detail=f"'{request.name}@{request.version}'은 이미 등록됨",
        )
    recipe = CleaningRecipe(
        name=request.name,
        version=request.version,
        description=request.description,
        steps=request.steps,
        created_at=_now_iso(),
    )
    payload = recipe.model_dump()
    payload.pop("name")
    payload.pop("version")
    versions[request.version] = payload
    save_recipes(raw)
    logger.info("레시피 등록: %s@%s (steps=%d)", request.name, request.version, len(request.steps))
    return recipe


def delete_recipe(name: str, version: str) -> None:
    raw = load_recipes()
    if name not in raw or version not in raw[name]:
        raise HTTPException(status_code=404, detail=f"레시피 '{name}@{version}' 없음")
    del raw[name][version]
    if not raw[name]:
        del raw[name]
    save_recipes(raw)


def list_versions(name: str) -> list[CleaningRecipe]:
    raw = load_recipes()
    if name not in raw:
        raise HTTPException(status_code=404, detail=f"레시피 '{name}' 없음")
    items = [CleaningRecipe(name=name, version=v, **p) for v, p in raw[name].items()]
    items.sort(key=lambda r: _semver_tuple(r.version), reverse=True)
    return items
