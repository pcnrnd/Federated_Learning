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


# ---------- 매핑표·정합성 단계 (F2) ----------

MAPPING = {
    "key": "id",
    "common_schema": {"id": {"type": "str"}, "x1": {"type": "float", "min": -30, "max": 30}},
    "sources": {"a": {"columns": {"rid": "id", "feat": "x1"}, "units": {"x1": "dx"}}},
    "units": {"x1": {"dx": {"scale": 0.1, "offset": -10}}},
    "codes": {},
}


def _mapped_recipe(mapping: dict | None = MAPPING) -> CleaningRecipeRequest:
    return CleaningRecipeRequest(
        name="hvc",
        version="1.0.0",
        steps=[
            CleaningStep(type="map_schema", params={"sources": ["a"]}),
            CleaningStep(type="validate_schema", params={"source": "a"}),
        ],
        mapping=mapping,
    )


@pytest.mark.unit
def test_register_recipe_stores_mapping_table():
    cleaning_recipe_service.register_recipe(_mapped_recipe())

    got = cleaning_recipe_service.get_recipe("hvc", "1.0.0").model_dump()

    assert got["mapping"]["sources"]["a"]["columns"] == {"rid": "id", "feat": "x1"}
    assert got["mapping"]["units"]["x1"]["dx"] == {"scale": 0.1, "offset": -10.0}
    assert got["mapping"]["common_schema"]["x1"]["min"] == -30


@pytest.mark.unit
def test_mapping_steps_require_mapping_table():
    with pytest.raises(HTTPException) as exc:
        cleaning_recipe_service.register_recipe(_mapped_recipe(mapping=None))
    assert exc.value.status_code == 400
    assert "매핑표" in exc.value.detail


@pytest.mark.unit
def test_map_schema_rejects_source_missing_from_mapping():
    request = _mapped_recipe()
    request.steps[0] = CleaningStep(type="map_schema", params={"sources": ["ghost"]})
    with pytest.raises(HTTPException) as exc:
        cleaning_recipe_service.register_recipe(request)
    assert exc.value.status_code == 400
    assert "ghost" in exc.value.detail


@pytest.mark.unit
@pytest.mark.parametrize(
    "patch",
    [
        {"key": "nope"},  # 키가 공통 스키마에 없음
        {"sources": {"a": {"columns": {"rid": "zzz"}}}},  # 대응 컬럼이 공통 스키마에 없음
        {"sources": {"a": {"columns": {"rid": "id"}, "units": {"id": "dx"}}}},  # 단위표에 없음
        {"sources": {"a": {"columns": {"rid": "id"}, "codes": {"id": "nope"}}}},  # 코드표 없음
    ],
)
def test_mapping_rejects_dangling_references(patch):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _mapped_recipe({**MAPPING, **patch})


@pytest.mark.unit
def test_server_step_catalog_matches_sdk_steps():
    from typing import get_args

    from models.cleaning_schemas import StepType
    from services.cleaning_recipes import STEP_CATALOG
    from silo_sdk.cleaning import SUPPORTED_STEPS

    assert set(STEP_CATALOG) == set(SUPPORTED_STEPS) == set(get_args(StepType))


# ---------- 교차 단계·전체 레시피 등록 (F5) ----------


@pytest.mark.unit
def test_full_hvc_recipe_registers_on_server():
    from silo_sdk import synthetic

    recipe = cleaning_recipe_service.register_recipe(
        CleaningRecipeRequest(name="silo-hvc", version="1.0.0", steps=synthetic.HVC_STEPS,
                              mapping=synthetic.HVC_MAPPING)
    )

    assert [s.type for s in recipe.steps] == [s["type"] for s in synthetic.HVC_STEPS]
    assert recipe.mapping.sources["records"].format == "records"


@pytest.mark.unit
@pytest.mark.parametrize(
    "step",
    [
        CleaningStep(type="parse_records", params={"source": "period_a", "into": "f"}),
        CleaningStep(type="map_schema", params={"sources": ["records"]}),
    ],
    ids=["records-step-on-table", "table-step-on-records"],
)
def test_source_format_must_match_step(step):
    from silo_sdk import synthetic

    with pytest.raises(HTTPException) as exc:
        cleaning_recipe_service.register_recipe(
            CleaningRecipeRequest(name="bad", version="1.0.0", steps=[step],
                                  mapping=synthetic.HVC_MAPPING)
        )
    assert exc.value.status_code == 400
    assert "형식" in exc.value.detail
