"""패키징 서비스 단위 테스트 (Docker SDK는 mock)"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from models.packaging_schemas import ModelRegisterRequest, PackagingRequest
from services import model_registry, packaging_service


@pytest.fixture()
def registered_model(tmp_path):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"fake-weights")
    return model_registry.register_model(
        ModelRegisterRequest(
            name="alpha",
            version="1.2.3",
            framework="pytorch",
            weights_path=str(weights),
        )
    )


@pytest.mark.unit
def test_render_dockerfile_includes_framework_and_tag(registered_model):
    request = PackagingRequest(model_name="alpha", version="1.2.3")

    rendered = packaging_service.render_dockerfile_only(request)

    assert "FROM python:3.11-slim" in rendered
    assert "MODEL_NAME=alpha" in rendered
    assert "MODEL_VERSION=1.2.3" in rendered
    assert "torch" in rendered  # pytorch 분기
    assert "uvicorn" in rendered


@pytest.mark.unit
def test_render_dockerfile_for_onnx_branch(tmp_path):
    weights = tmp_path / "m.onnx"
    weights.write_bytes(b"")
    model_registry.register_model(
        ModelRegisterRequest(
            name="beta",
            version="0.1.0",
            framework="onnx",
            weights_path=str(weights),
        )
    )
    request = PackagingRequest(model_name="beta", version="0.1.0")

    rendered = packaging_service.render_dockerfile_only(request)

    assert "onnxruntime" in rendered
    assert "torch" not in rendered


@pytest.mark.unit
def test_build_package_invokes_docker_with_expected_tag(registered_model):
    fake_image = MagicMock()
    fake_image.attrs = {"Size": 12345}
    fake_client = MagicMock()
    fake_client.images.build.return_value = (fake_image, iter([]))

    request = PackagingRequest(model_name="alpha", version="1.2.3")

    with patch("services.packaging_service.docker.from_env", return_value=fake_client):
        result = packaging_service.build_package(request)

    assert result.image_tag == "fed-model-alpha:1.2.3"
    assert result.image_size_bytes == 12345
    fake_client.images.build.assert_called_once()
    build_kwargs = fake_client.images.build.call_args.kwargs
    assert build_kwargs["tag"] == "fed-model-alpha:1.2.3"
    ctx = Path(build_kwargs["path"])
    # 컨텍스트는 임시디렉이라 호출 후엔 사라짐 — 호출 시점에 존재했음을 보장하기 위해
    # path가 절대경로 문자열인지만 확인한다.
    assert ctx.is_absolute()


@pytest.mark.unit
def test_build_package_with_custom_tag(registered_model):
    fake_image = MagicMock()
    fake_image.attrs = {"Size": 1}
    fake_client = MagicMock()
    fake_client.images.build.return_value = (fake_image, iter([]))

    request = PackagingRequest(
        model_name="alpha",
        version="1.2.3",
        image_tag="custom/repo:tag",
    )

    with patch("services.packaging_service.docker.from_env", return_value=fake_client):
        result = packaging_service.build_package(request)

    assert result.image_tag == "custom/repo:tag"
