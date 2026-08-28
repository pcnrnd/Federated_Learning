"""정제 레시피 단위 테스트"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.cleaning_schemas import CleaningRecipeRequest, CleaningStep
from services import cleaning_recipe_service


def _recipe(name: str = "hospital", version: str = "1.0.0") -> CleaningRecipeRequest:
    return CleaningRecipeRequest(
        name=name,
        version=version,
        description="basic recipe",
        steps=[
            CleaningStep(type="drop_nulls", params={"columns": ["age"]}),
            CleaningStep(type="dedupe", params={"keys": ["patient_id"]}),
        ],
    )


@pytest.mark.unit
def test_register_and_get_recipe():
    cleaning_recipe_service.register_recipe(_recipe())

    got = cleaning_recipe_service.get_recipe("hospital", "1.0.0")

    assert len(got.steps) == 2
    assert got.steps[0].type == "drop_nulls"


@pytest.mark.unit
def test_register_rejects_invalid_step_params():
    with pytest.raises(HTTPException) as exc:
        cleaning_recipe_service.register_recipe(
            CleaningRecipeRequest(
                name="bad",
                version="1.0.0",
                steps=[CleaningStep(type="drop_nulls", params={})],  # columns 누락
            )
        )
    assert exc.value.status_code == 400


@pytest.mark.unit
def test_register_duplicate_version_returns_409():
    cleaning_recipe_service.register_recipe(_recipe())
    with pytest.raises(HTTPException) as exc:
        cleaning_recipe_service.register_recipe(_recipe())
    assert exc.value.status_code == 409


@pytest.mark.unit
def test_register_rejects_unknown_step_type():
    with pytest.raises(Exception):
        cleaning_recipe_service.register_recipe(
            CleaningRecipeRequest(
                name="x",
                version="1.0.0",
                steps=[CleaningStep(type="ghost_step", params={})],  # type: ignore[arg-type]
            )
        )


@pytest.mark.unit
def test_list_versions_sorted_desc():
    for v in ("1.0.0", "1.2.0", "1.1.0"):
        cleaning_recipe_service.register_recipe(_recipe(version=v))

    versions = [r.version for r in cleaning_recipe_service.list_versions("hospital")]

    assert versions == ["1.2.0", "1.1.0", "1.0.0"]


@pytest.mark.unit
def test_delete_recipe_removes_entry():
    cleaning_recipe_service.register_recipe(_recipe())

    cleaning_recipe_service.delete_recipe("hospital", "1.0.0")

    with pytest.raises(HTTPException):
        cleaning_recipe_service.get_recipe("hospital", "1.0.0")
