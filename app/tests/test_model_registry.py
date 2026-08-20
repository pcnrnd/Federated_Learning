"""모델 레지스트리 단위 테스트"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.packaging_schemas import ModelRegisterRequest
from services import model_registry


def _req(name: str = "m1", version: str = "1.0.0") -> ModelRegisterRequest:
    return ModelRegisterRequest(
        name=name,
        version=version,
        framework="pytorch",
        weights_path="/tmp/m.pt",
    )


@pytest.mark.unit
def test_register_then_get():
    entry = model_registry.register_model(_req("alpha", "1.0.0"))

    assert entry.name == "alpha"
    assert entry.version == "1.0.0"
    assert entry.created_at  # ISO-8601 timestamp 존재

    got = model_registry.get_model("alpha", "1.0.0")
    assert got.framework == "pytorch"


@pytest.mark.unit
def test_register_duplicate_raises_409():
    model_registry.register_model(_req("alpha", "1.0.0"))
    with pytest.raises(HTTPException) as exc:
        model_registry.register_model(_req("alpha", "1.0.0"))
    assert exc.value.status_code == 409


@pytest.mark.unit
def test_list_versions_sorted_desc():
    model_registry.register_model(_req("m", "1.0.0"))
    model_registry.register_model(_req("m", "2.0.0"))
    model_registry.register_model(_req("m", "1.5.3"))

    versions = [v.version for v in model_registry.list_versions("m")]

    assert versions == ["2.0.0", "1.5.3", "1.0.0"]


@pytest.mark.unit
def test_latest_version_returns_highest_semver():
    model_registry.register_model(_req("m", "0.9.10"))
    model_registry.register_model(_req("m", "1.2.0"))
    model_registry.register_model(_req("m", "1.10.0"))

    latest = model_registry.latest_version("m")

    assert latest.version == "1.10.0"


@pytest.mark.unit
def test_delete_model_removes_entry_and_collapses_empty_name():
    model_registry.register_model(_req("m", "1.0.0"))

    model_registry.delete_model("m", "1.0.0")

    with pytest.raises(HTTPException):
        model_registry.get_model("m", "1.0.0")
    assert model_registry.list_models() == []


@pytest.mark.unit
def test_register_rejects_invalid_semver():
    with pytest.raises(Exception):  # pydantic ValidationError
        ModelRegisterRequest(
            name="m",
            version="v1.0",
            framework="pytorch",
            weights_path="/tmp/m.pt",
        )


@pytest.mark.unit
def test_get_unknown_model_returns_404():
    with pytest.raises(HTTPException) as exc:
        model_registry.get_model("missing", "1.0.0")
    assert exc.value.status_code == 404
