"""사일로 SDK 단위 테스트 (urllib 레벨에서 mock)"""
from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# silo_sdk는 app/silo_sdk/ 에 위치 — app/ 디렉토리를 sys.path에 추가하면 import 가능
SDK_PARENT = Path(__file__).resolve().parent.parent  # app/tests/* → app/
if str(SDK_PARENT) not in sys.path:
    sys.path.insert(0, str(SDK_PARENT))

from silo_sdk import SiloClient, SiloClientError, build_histogram, edge  # noqa: E402


def _ok_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@pytest.mark.unit
def test_build_histogram_counts_values_into_bins():
    counts = build_histogram(
        [0.5, 1.5, 1.7, 2.5, 5.0],
        bin_edges=[0.0, 1.0, 2.0, 3.0],
    )
    # 0.5 -> bin0, 1.5/1.7 -> bin1, 2.5 -> bin2, 5.0 -> bin2(clip)
    assert counts == [1, 2, 2]


@pytest.mark.unit
def test_build_histogram_rejects_non_monotonic_edges():
    with pytest.raises(ValueError):
        build_histogram([1.0], bin_edges=[1.0, 1.0])


@pytest.mark.unit
def test_push_metric_calls_correct_endpoint_with_payload():
    captured: dict = {}

    def _fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _ok_response({"ok": True})

    client = SiloClient("http://central:8000", silo_id="silo-2")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        result = client.push_metric("alpha", "1.0.0", "accuracy", 0.95)

    assert result == {"ok": True}
    assert captured["url"] == "http://central:8000/api/monitoring/metrics"
    assert captured["method"] == "POST"
    assert captured["body"]["node_id"] == "silo-2"
    assert captured["body"]["metric"] == "accuracy"
    assert captured["body"]["value"] == 0.95


@pytest.mark.unit
def test_client_sends_api_key_header_when_configured():
    captured: dict = {}

    def _fake_urlopen(req, timeout):
        captured["api_key"] = req.get_header("X-fed-api-key")
        return _ok_response({"ok": True})

    client = SiloClient("http://central:8000", silo_id="silo-2", api_key="secret")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        client.push_metric("alpha", "1.0.0", "accuracy", 0.95)

    assert captured["api_key"] == "secret"


@pytest.mark.unit
def test_push_distribution_sends_histogram_only():
    captured: dict = {}

    def _fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _ok_response({"psi": 0.05, "severity": "stable"})

    client = SiloClient("http://central:8000", silo_id="silo-2")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        client.push_distribution(
            "alpha",
            "1.0.0",
            feature="age",
            bin_edges=[0.0, 10.0, 20.0],
            bin_counts=[100, 100],
        )

    body = captured["body"]
    assert captured["url"] == "http://central:8000/api/monitoring/drift"
    assert "bin_counts" in body and "bin_edges" in body
    # 원시 데이터 필드가 절대 들어가지 않음을 확인
    assert "raw" not in body
    assert "values" not in body


@pytest.mark.unit
def test_push_parameters_routes_to_round_contribution():
    captured: dict = {}

    def _fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _ok_response({"round_id": "r1"})

    client = SiloClient("http://central:8000", silo_id="silo-2")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        client.push_parameters("r1", sample_count=42, parameters=[1.0, 2.0, 3.0])

    assert captured["url"] == "http://central:8000/api/training-rounds/r1/contributions"
    assert captured["body"]["silo_id"] == "silo-2"
    assert captured["body"]["sample_count"] == 42
    assert captured["body"]["parameters"] == [1.0, 2.0, 3.0]


@pytest.mark.unit
def test_http_4xx_raises_silo_client_error():
    import urllib.error

    err = urllib.error.HTTPError(
        url="http://central:8000/api/monitoring/metrics",
        code=404,
        msg="Not Found",
        hdrs=None,  # type: ignore[arg-type]
        fp=BytesIO(b'{"detail":"not found"}'),
    )
    client = SiloClient("http://central:8000", silo_id="silo-2", retries=0)
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=err):
        with pytest.raises(SiloClientError) as exc:
            client.push_metric("alpha", "1.0.0", "accuracy", 0.5)
    assert exc.value.status == 404


@pytest.mark.unit
def test_5xx_retries_then_raises():
    import urllib.error

    def _failing(req, timeout):
        raise urllib.error.HTTPError(
            url=req.full_url,
            code=503,
            msg="Service Unavailable",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(b"down"),
        )

    client = SiloClient(
        "http://central:8000", silo_id="silo-2", retries=2, timeout=0.1
    )
    with (
        patch("silo_sdk.client.urllib.request.urlopen", side_effect=_failing) as urlopen,
        patch("silo_sdk.client.time.sleep"),
    ):
        with pytest.raises(SiloClientError):
            client.push_metric("alpha", "1.0.0", "accuracy", 0.5)

    # retries=2 → 총 3회 시도
    assert urlopen.call_count == 3


@pytest.mark.unit
def test_list_metrics_unwraps_paginated_items():
    """PaginatedResponse의 items 키만 반환한다."""
    payload = {
        "items": [{"metric": "accuracy", "value": 0.9}],
        "total": 1,
        "offset": 0,
        "limit": 100,
    }

    def _fake_urlopen(req, timeout):
        return _ok_response(payload)

    client = SiloClient("http://central:8000", silo_id="silo-2")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        items = client.list_metrics("alpha", "1.0.0")

    assert len(items) == 1
    assert items[0]["metric"] == "accuracy"


@pytest.mark.unit
def test_list_rounds_filters_by_status_and_model():
    """status/model_name 쿼리로 라운드 목록을 조회하고 리스트를 그대로 반환한다."""
    captured: dict = {}

    def _fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        return _ok_response([{"round_id": "r1", "status": "open", "contributors": []}])

    client = SiloClient("http://central:8000", silo_id="silo-2")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        rounds = client.list_rounds(status="open", model_name="e2e-ridge")

    assert captured["method"] == "GET"
    assert captured["url"] == "http://central:8000/api/training-rounds?status=open&model_name=e2e-ridge"
    assert rounds == [{"round_id": "r1", "status": "open", "contributors": []}]


@pytest.mark.unit
def test_list_rounds_without_filters_hits_bare_path():
    def _fake_urlopen(req, timeout):
        assert req.full_url == "http://central:8000/api/training-rounds"
        return _ok_response([])

    client = SiloClient("http://central:8000", silo_id="silo-2")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        assert client.list_rounds() == []


@pytest.mark.unit
def test_post_sends_idempotency_key_header():
    """POST 요청에 X-Idempotency-Key 헤더를 붙일 수 있다."""
    captured: dict = {}

    def _fake_urlopen(req, timeout):
        captured["idem"] = req.get_header("X-idempotency-key")
        return _ok_response({"ok": True})

    client = SiloClient("http://central:8000", silo_id="silo-2")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        client.push_metric(
            "alpha", "1.0.0", "accuracy", 0.95, idempotency_key="idem-abc"
        )

    assert captured["idem"] == "idem-abc"


# ---------- 엣지 집계 combine (HFL 설계 스펙 §4.3) ----------


@pytest.mark.unit
def test_combine_returns_sample_sum_and_weighted_average():
    total, params = edge.combine(
        [("silo-3", 30, [2.0, 6.0]), ("silo-4", 10, [10.0, 2.0])]
    )

    assert total == 40
    assert params == pytest.approx([4.0, 5.0])


@pytest.mark.unit
def test_combine_equal_samples_is_plain_average():
    total, params = edge.combine([("a", 5, [0.0, 2.0]), ("b", 5, [2.0, 0.0])])

    assert total == 10
    assert params == pytest.approx([1.0, 1.0])


@pytest.mark.unit
def test_combine_rejects_dimension_mismatch():
    with pytest.raises(ValueError, match="차원 불일치"):
        edge.combine([("a", 1, [1.0, 2.0]), ("b", 1, [1.0])])


@pytest.mark.unit
def test_combine_rejects_non_positive_sample_count():
    with pytest.raises(ValueError):
        edge.combine([("a", 0, [1.0])])
    with pytest.raises(ValueError):
        edge.combine([("a", -3, [1.0])])


@pytest.mark.unit
def test_combine_rejects_empty_children():
    with pytest.raises(ValueError):
        edge.combine([])


@pytest.mark.unit
def test_combine_rejects_empty_parameter_vector():
    with pytest.raises(ValueError):
        edge.combine([("a", 1, [])])


@pytest.mark.unit
def test_push_parameters_forwards_aggregated_from():
    captured: dict = {}

    def _fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _ok_response({"round_id": "r1"})

    client = SiloClient("http://central:8000", silo_id="silo-1")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        client.push_parameters(
            "r1",
            sample_count=40,
            parameters=[4.0, 5.0],
            aggregated_from=["silo-3", "silo-4"],
        )

    assert captured["body"]["aggregated_from"] == ["silo-3", "silo-4"]
    assert captured["body"]["sample_count"] == 40


@pytest.mark.unit
def test_push_parameters_defaults_to_empty_aggregated_from():
    """기존 호출은 무변경 — 하위 목록 없이 빈 목록으로 나간다"""
    captured: dict = {}

    def _fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _ok_response({"round_id": "r1"})

    client = SiloClient("http://central:8000", silo_id="silo-2")
    with patch("silo_sdk.client.urllib.request.urlopen", side_effect=_fake_urlopen):
        client.push_parameters("r1", sample_count=42, parameters=[1.0])

    assert captured["body"]["aggregated_from"] == []
