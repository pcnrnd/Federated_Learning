"""모델 lineage 단위 테스트"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.maintenance_schemas import ModelLineageRequest
from models.packaging_schemas import ModelRegisterRequest
from services import lineage_service, model_registry


@pytest.fixture(autouse=True)
def _register_versions(tmp_path):
    weights = tmp_path / "m.pt"
    weights.write_bytes(b"")
    for v in ("1.0.0", "1.1.0", "1.2.0", "2.0.0"):
        model_registry.register_model(
            ModelRegisterRequest(
                name="alpha",
                version=v,
                framework="pytorch",
                weights_path=str(weights),
            )
        )


@pytest.mark.unit
def test_set_lineage_requires_parent_in_registry():
    with pytest.raises(HTTPException) as exc:
        lineage_service.set_lineage(
            "alpha",
            "1.1.0",
            ModelLineageRequest(parent_version="9.9.9", change_type="minor"),
        )
    assert exc.value.status_code == 404


@pytest.mark.unit
def test_get_lineage_returns_recorded_entry():
    lineage_service.set_lineage(
        "alpha",
        "1.1.0",
        ModelLineageRequest(parent_version="1.0.0", change_type="minor", change_notes="add layer"),
    )

    got = lineage_service.get_lineage("alpha", "1.1.0")

    assert got.parent_version == "1.0.0"
    assert got.change_type == "minor"
    assert got.change_notes == "add layer"


@pytest.mark.unit
def test_ancestors_returns_chain_to_root():
    lineage_service.set_lineage(
        "alpha", "1.1.0", ModelLineageRequest(parent_version="1.0.0")
    )
    lineage_service.set_lineage(
        "alpha", "1.2.0", ModelLineageRequest(parent_version="1.1.0")
    )

    chain = lineage_service.ancestors("alpha", "1.2.0")

    assert [c.version for c in chain] == ["1.1.0", "1.0.0"]


@pytest.mark.unit
def test_lineage_tree_groups_versions_under_parents():
    lineage_service.set_lineage(
        "alpha", "1.1.0", ModelLineageRequest(parent_version="1.0.0", change_type="minor")
    )
    lineage_service.set_lineage(
        "alpha", "1.2.0", ModelLineageRequest(parent_version="1.1.0", change_type="minor")
    )
    # 2.0.0 은 부모 미지정 (별도 루트)

    tree = lineage_service.lineage_tree("alpha")

    roots = {n.version: n for n in tree}
    assert "1.0.0" in roots and "2.0.0" in roots
    one_oh = roots["1.0.0"]
    assert [c.version for c in one_oh.children] == ["1.1.0"]
    assert [c.version for c in one_oh.children[0].children] == ["1.2.0"]
