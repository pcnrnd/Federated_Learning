"""정제 레시피 API"""
from __future__ import annotations

from fastapi import APIRouter

from models.cleaning_schemas import CleaningRecipe, CleaningRecipeRequest
from services import cleaning_recipe_service

router = APIRouter(prefix="/api/cleaning-recipes", tags=["cleaning-recipes"])


@router.get("", response_model=list[CleaningRecipe])
def list_recipes_endpoint() -> list[CleaningRecipe]:
    return cleaning_recipe_service.list_recipes()


@router.post("", response_model=CleaningRecipe, status_code=201)
def register_recipe_endpoint(request: CleaningRecipeRequest) -> CleaningRecipe:
    return cleaning_recipe_service.register_recipe(request)


@router.get("/{name}/versions", response_model=list[CleaningRecipe])
def list_versions_endpoint(name: str) -> list[CleaningRecipe]:
    return cleaning_recipe_service.list_versions(name)


@router.get("/{name}/{version}", response_model=CleaningRecipe)
def get_recipe_endpoint(name: str, version: str) -> CleaningRecipe:
    return cleaning_recipe_service.get_recipe(name, version)


@router.delete("/{name}/{version}")
def delete_recipe_endpoint(name: str, version: str) -> dict[str, bool]:
    cleaning_recipe_service.delete_recipe(name, version)
    return {"ok": True}
