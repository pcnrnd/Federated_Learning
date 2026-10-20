"""실제 정제 카운트→저장 정책→PSI/경고의 수치·저장 실패·동시성 회귀."""
from __future__ import annotations

import copy
import importlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from main import app
from models.distribution_schemas import DistributionPolicyRequest
from services import distribution_drift as drift, distribution_service as ledger
from storage.factory import reset_repositories
from test_distribution_reports import PRIVATE, config_for, output, report_for
import test_distribution_reports as distribution_fixtures

# pytest가 수집할 동일 fixture 객체를 원래 이름으로 재노출한다.
world = distribution_fixtures.world

NOW = datetime(2026, 10, 20, 0, 10, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    monkeypatch.setattr(drift, "_now", lambda: NOW)


def policy(config, **changes):
    value = {"config_id": config["config_id"], "warning_threshold": 0.1,
             "critical_threshold": 0.25, "min_valid_count": 1, "max_age_seconds": 3600}
    return drift.put_policy(dict(value, **changes))


def prepared(world):
    manifest, shard = output(world, "base", values=[1, 2, 11, 12])
    config = config_for(world, manifest)
    reference = report_for(world, manifest, shard, config)
    ledger.accept_report(reference)
    baseline = ledger.select_baseline(reference["report_id"])
    policy(config)
    return config, reference, baseline


def change(world, config, identity="changed", *, values=None, completed_at="2026-10-20T00:02:30+00:00"):
    manifest, shard = output(world, identity, values=values or [1, 11, 12, 13], completed_at=completed_at)
    report = report_for(world, manifest, shard, config)
    ledger.accept_report(report)
    return report


def current():
    return drift.overview()["items"][0]


def test_actual_cleaned_histograms_have_independently_calculated_psi_and_exact_lineage(world):
    config, reference, baseline = prepared(world)
    report = change(world, config)
    event = current()
    # 기준(1/2,1/2)→현재(1/4,3/4): (1/4)*log(3). 구현 계산 함수를 기대값으로 쓰지 않는다.
    assert event["psi"] == pytest.approx(math.log(3) / 4, rel=1e-12)
    assert event["state"] == "ready" and event["severity"] == "critical"
    assert event["baseline_bin_counts"] == [2, 2] and event["current_bin_counts"] == [1, 3]
    assert (event["current_total_count"], event["current_valid_count"], event["current_excluded_count"]) == (4, 4, 0)
    assert event["current_report_id"] == report["report_id"] and event["baseline_id"] == baseline["baseline_id"]
    assert event["baseline_report_id"] == reference["report_id"] and event["policy"]["policy_version"] == 1
    assert (event["model_name"], event["version"], event["feature"], event["node_id"]) == ("m", "1.0.0", "x", "silo-1")
    assert event["window_start"] == report["window_start"] and event["baseline_at"] == reference["completed_at"]
    serialized = json.dumps(ledger._load())
    assert PRIVATE not in serialized and "987654.321098765" not in serialized
    assert all(key not in serialized for key in ('"rows":', '"targets":', '"inputs":'))


def test_saved_threshold_boundaries_and_changed_policy_preserve_event_history(world):
    config, _, _ = prepared(world)
    change(world, config)
    first = copy.deepcopy(current())
    psi = first["psi"]
    saved = policy(config, warning_threshold=psi, critical_threshold=psi + 1)
    assert current()["severity"] == "warning"  # 경고 경계 포함.
    assert saved["policy_version"] == 2
    assert policy(config, warning_threshold=psi, critical_threshold=psi + 1) == saved
    policy(config, warning_threshold=psi / 2, critical_threshold=psi)
    assert current()["severity"] == "critical"  # 경보 경계 포함.
    policy(config, warning_threshold=psi + 0.1, critical_threshold=psi + 1)
    assert current()["severity"] == "stable"
    history = drift.events(config["config_id"], "silo-1")
    assert next(item for item in history if item["event_id"] == first["event_id"]) == first
    assert len(ledger._load()["drift_policies"]) == 4


def test_identical_distribution_is_measured_zero_not_missing_zero(world):
    config, _, _ = prepared(world)
    change(world, config, values=[1, 2, 11, 12])
    assert (current()["state"], current()["psi"], current()["severity"]) == ("ready", 0, "stable")
    assert drift.overview()["alerts"] == []


def test_real_zero_bins_use_existing_epsilon_psi_without_percent_clamping(world):
    manifest, shard = output(world, "base", values=[1, 2, 3, 4])
    config = config_for(world, manifest)
    reference = report_for(world, manifest, shard, config)
    ledger.accept_report(reference)
    ledger.select_baseline(reference["report_id"])
    policy(config, warning_threshold=1, critical_threshold=2)
    change(world, config, values=[11, 12, 13, 14])
    assert current()["psi"] == pytest.approx(2 * (1 - 1e-6) * math.log(1_000_000), rel=1e-12)
    assert current()["psi"] > 1 and current()["severity"] == "critical"


def test_minimum_count_uses_training_valid_rows_not_total_rows(world):
    manifest, shard = output(world, "base", values=[1, 2, 11, 12, PRIVATE])
    config = config_for(world, manifest)
    reference = report_for(world, manifest, shard, config)
    assert (reference["total_count"], reference["valid_count"], reference["excluded_count"]) == (5, 4, 1)
    ledger.accept_report(reference)
    ledger.select_baseline(reference["report_id"])
    change(world, config, values=[1, 11, "NaN", "", PRIVATE])
    policy(config, min_valid_count=3)
    event = current()
    assert event["baseline_valid_count"] >= 3
    assert (event["current_total_count"], event["current_valid_count"], event["current_excluded_count"]) == (5, 2, 3)
    assert event["state"] == "insufficient" and event["psi"] is None


def test_late_older_report_does_not_rewind_or_resolve_newer_drift(world):
    config, _, _ = prepared(world)
    latest = change(world, config, completed_at="2026-10-20T00:03:30+00:00")
    event = copy.deepcopy(current())
    change(world, config, "late", values=[1, 2, 11, 12], completed_at="2026-10-20T00:02:30+00:00")
    assert current() == event and current()["current_report_id"] == latest["report_id"]
    assert len(drift.overview()["alerts"]) == 1 and drift.overview()["alerts"][0]["status"] == "open"


@pytest.mark.parametrize("missing", ["policy", "baseline", "current"])
def test_missing_prerequisite_has_no_normal_psi(world, missing):
    config, _, _ = prepared(world)
    state = ledger._load()
    section = {"policy": "drift_policy_current", "baseline": "baseline_current", "current": "current"}[missing]
    state[section].clear()
    ledger._save(state)
    event = current()
    assert event["state"] == {"policy": "unconfigured", "baseline": "missing_baseline", "current": "missing_current"}[missing]
    assert event["psi"] is None and event["severity"] is None


@pytest.mark.parametrize("field,value", [("bin_edges", [0, 9, 20]), ("schema_fingerprint", "a" * 64),
    ("bin_counts", [0, 0]), ("bin_counts", [True, 3]), ("node_id", "silo-2")])
def test_incompatible_stored_observation_is_visible_invalid_not_stable(world, field, value):
    config, _, _ = prepared(world)
    report = change(world, config)
    state = ledger._load()
    state["reports"][report["report_id"]][field] = value
    ledger._save(state)
    event = current()
    assert event["state"] == "invalid" and event["psi"] is None and event["severity"] is None
    assert any(a["event_id"] == event["event_id"] and a["cause"] == "invalid" for a in drift.overview()["alerts"])


def test_age_boundary_and_insufficient_samples_never_become_normal_zero(world, monkeypatch):
    config, _, _ = prepared(world)
    report = change(world, config)
    policy(config, max_age_seconds=60)
    assert current()["state"] == "stale" and current()["psi"] is None
    boundary = datetime.fromisoformat(report["completed_at"]) + timedelta(seconds=60)
    monkeypatch.setattr(drift, "_now", lambda: boundary)
    assert current()["state"] == "ready"
    monkeypatch.setattr(drift, "_now", lambda: boundary + timedelta(microseconds=1))
    assert current()["state"] == "stale"
    monkeypatch.setattr(drift, "_now", lambda: NOW)
    policy(config, min_valid_count=5)
    assert current()["state"] == "insufficient" and current()["psi"] is None


def test_future_observation_is_not_fresh_forever(world, monkeypatch):
    config, _, _ = prepared(world)
    change(world, config)
    monkeypatch.setattr(drift, "_now", lambda: datetime(2026, 10, 20, 0, 2, tzinfo=timezone.utc))
    assert current()["state"] == "invalid" and current()["psi"] is None


def test_duplicate_report_and_concurrent_evaluation_emit_one_alert_and_keep_ack_after_reload(world, monkeypatch):
    config, _, _ = prepared(world)
    report = change(world, config)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: (ledger.accept_report(report), drift.overview()), range(12)))
    alert = drift.overview()["alerts"][0]
    assert len(drift.overview()["alerts"]) == 1
    assert drift.ack(alert["alert_id"])["status"] == "acked"
    reset_repositories()
    importlib.reload(drift)
    monkeypatch.setattr(drift, "_now", lambda: NOW)
    assert current()["event_id"] == alert["event_id"]
    assert drift.overview()["alerts"][0]["status"] == "acked"
    assert drift.ack(alert["alert_id"])["status"] == "acked"


def test_ack_is_not_resolve_normal_observation_resolves_and_new_drift_is_new_event(world):
    config, _, _ = prepared(world)
    change(world, config)
    alert = drift.overview()["alerts"][0]
    drift.ack(alert["alert_id"])
    assert drift.overview()["alerts"][0]["resolved_at"] is None
    change(world, config, "normal", values=[1, 2, 11, 12], completed_at="2026-10-20T00:03:30+00:00")
    resolved = drift.ack(alert["alert_id"])
    assert resolved["status"] == "resolved" and resolved["resolved_by_event_id"] == current()["event_id"]
    assert resolved["resolved_at"] == NOW.isoformat() and resolved["acked_at"] is not None
    reset_repositories()
    assert drift.overview()["alerts"][0] == resolved
    change(world, config, "recurrence", completed_at="2026-10-20T00:04:30+00:00")
    alerts = drift.overview()["alerts"]
    assert len(alerts) == 2 and {a["status"] for a in alerts} == {"open", "resolved"}


def test_baseline_a_b_a_has_distinct_selection_revision_without_rewriting_old_comparison(world):
    config, reference, _ = prepared(world)
    report = change(world, config)
    old = copy.deepcopy(current())
    ledger.select_baseline(report["report_id"])
    assert current()["severity"] == "stable"
    ledger.select_baseline(reference["report_id"])
    new = current()
    assert new["severity"] == "critical" and new["event_id"] != old["event_id"]
    assert new["basis_revision"] > old["basis_revision"]
    assert len(drift.overview()["alerts"]) == 2
    assert next(e for e in drift.events(config["config_id"], "silo-1") if e["event_id"] == old["event_id"]) == old


@pytest.mark.parametrize("operation", ["policy", "report", "baseline", "ack"])
def test_save_failure_has_no_published_event_policy_or_ack_and_retry_uses_durable_state(world, monkeypatch, operation):
    config, reference, _ = prepared(world)
    report = change(world, config)
    before = copy.deepcopy(ledger._load())
    alert_id = drift.overview()["alerts"][0]["alert_id"]
    original = ledger._save
    def fail(_state):
        raise OSError("selective ledger save failure")
    monkeypatch.setattr(ledger, "_save", fail)
    pending = None
    if operation == "report":
        manifest, shard = output(world, "pending", values=[1, 11, 12, 13], completed_at="2026-10-20T00:04:30+00:00")
        pending = report_for(world, manifest, shard, config)
    def action():
        if operation == "policy":
            return policy(config, critical_threshold=2)
        if operation == "baseline":
            return ledger.select_baseline(report["report_id"])
        if operation == "ack":
            return drift.ack(alert_id)
        return ledger.accept_report(pending)
    with pytest.raises(OSError):
        action()
    assert ledger._load() == before
    reset_repositories()
    monkeypatch.setattr(ledger, "_save", original)
    action()
    assert ledger._load() != before
    assert ledger.get_report(reference["report_id"])["bin_counts"] == [2, 2]


def test_old_g6a_ledger_is_readable_and_additive_upgrade_preserves_reports_and_baselines(world):
    config, reference, baseline = prepared(world)
    state = ledger._load()
    legacy = {key: state[key] for key in ledger._LEGACY_SECTIONS}
    ledger._save(legacy)
    assert ledger.get_current(config["config_id"], "silo-1") == reference
    assert ledger.get_baseline(baseline["baseline_id"]) == baseline
    assert current()["state"] == "unconfigured"
    policy(config)
    reset_repositories()
    assert current()["severity"] == "stable"


@pytest.mark.parametrize("changes", [{"warning_threshold": True}, {"critical_threshold": float("inf")},
    {"critical_threshold": 0.1}, {"min_valid_count": 0}, {"max_age_seconds": 1.1}, {"rows": []}])
def test_policy_rejects_invalid_or_raw_fields(changes):
    value = {"config_id": "a" * 64, "warning_threshold": 0.1, "critical_threshold": 0.25,
             "min_valid_count": 1, "max_age_seconds": 60}
    with pytest.raises(ValidationError):
        DistributionPolicyRequest(**dict(value, **changes))


def test_api_returns_real_comparison_persisted_policy_ack_and_missing_state(world):
    config, _, _ = prepared(world)
    change(world, config)
    client = TestClient(app)
    response = client.get("/api/monitoring/distributions/drift")
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["psi"] == pytest.approx(math.log(3) / 4)
    alert = body["alerts"][0]
    assert client.post(f"/api/monitoring/distributions/alerts/{alert['alert_id']}/ack").json()["status"] == "acked"
    assert client.get("/api/monitoring/distributions/events", params={"config_id": config["config_id"], "node_id": "silo-1"}).status_code == 200
    assert client.post("/api/monitoring/distributions/policies", json={"config_id": config["config_id"],
        "warning_threshold": 2, "critical_threshold": 3, "min_valid_count": 1, "max_age_seconds": 3600}).json()["policy_version"] == 2
    assert client.get("/api/monitoring/distributions/drift").json()["alerts"][0]["status"] == "resolved"
    assert PRIVATE not in json.dumps(body)
