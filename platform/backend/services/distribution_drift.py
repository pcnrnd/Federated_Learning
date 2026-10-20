"""검증된 분포와 정책/경고를 같은 원자 원장에 연결한다. 원시 행은 받지 않는다."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from models.distribution_schemas import DistributionPolicyRequest
from services import distribution_service as ledger
from services.drift_detector import compute_psi
from silo_sdk.distributions import sha, validate_report


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _scope(config_id: str, node_id: str) -> str:
    return sha([config_id, node_id])


def _context(state: dict, config_id: str, node_id: str) -> tuple[dict, dict | None, dict | None, dict | None]:
    config = ledger._required(state, "configs", config_id)
    if node_id not in config["node_ids"]:
        raise HTTPException(422, "설정 범위 밖 사일로입니다")
    key = _scope(config_id, node_id)
    policy = state["drift_policies"].get(state["drift_policy_current"].get(config_id, ""))
    baseline = state["baselines"].get(state["baseline_current"].get(key, ""))
    current = state["reports"].get(state["current"].get(key, ""))
    return config, policy, baseline, current


def _compare(config: dict, policy: dict, baseline: dict, current: dict, now: datetime) -> dict:
    if policy is None:
        return {"state": "unconfigured", "reason": "저장된 비교 정책이 없습니다"}
    if baseline is None:
        return {"state": "missing_baseline", "reason": "명시적으로 선택한 기준 관측이 없습니다"}
    if current is None:
        return {"state": "missing_current", "reason": "검증된 현재 관측이 없습니다"}
    try:
        reference = baseline["report"]
        validate_report(reference, config)
        validate_report(current, config)
        if (baseline["config_id"] != current["config_id"]
                or baseline["node_id"] != current["node_id"]
                or reference["node_id"] != current["node_id"]
                or baseline["report_id"] != reference["report_id"]
                or baseline["baseline_id"] != sha(["baseline-v1", reference["report_id"]])):
            raise ValueError()
        at = datetime.fromisoformat(current["completed_at"])
        if at > now:
            return {"state": "invalid", "reason": "현재 관측 시각이 서버 시각보다 미래입니다"}
        if (now - at).total_seconds() > policy["max_age_seconds"]:
            return {"state": "stale", "reason": "현재 관측의 유효 시간이 지났습니다"}
        if min(reference["valid_count"], current["valid_count"]) < policy["min_valid_count"]:
            return {"state": "insufficient", "reason": "저장된 최소 유효 표본 수를 충족하지 않습니다"}
        psi = compute_psi(reference["bin_counts"], current["bin_counts"])
    except (KeyError, ValueError, TypeError, OverflowError):
        return {"state": "invalid", "reason": "기준/현재의 공통 bin·schema·개수·해시가 불일치합니다"}
    severity = ("critical" if psi >= policy["critical_threshold"] else
                "warning" if psi >= policy["warning_threshold"] else "stable")
    return {"state": "ready", "reason": f"PSI {psi:.6g} (경고 {policy['warning_threshold']}, 경보 {policy['critical_threshold']})",
            "psi": psi, "severity": severity}


def _observation(config: dict, node_id: str, policy: dict, baseline: dict, current: dict,
                 now: datetime) -> dict:
    compared = _compare(config, policy, baseline, current, now)
    reference = baseline.get("report", {}) if baseline else {}
    body = {"config_id": config["config_id"], "node_id": node_id, "model_name": config["model_name"],
            "version": config["version"], "feature": config["feature"], "policy": policy,
            "baseline_id": baseline.get("baseline_id") if baseline else None,
            "baseline_report_id": reference.get("report_id"),
            "current_report_id": current.get("report_id") if current else None,
            "baseline_at": reference.get("completed_at"), "current_at": (current or {}).get("completed_at"),
            "window_start": (current or {}).get("window_start"), "window_end": (current or {}).get("window_end"),
            "baseline_window_start": reference.get("window_start"), "baseline_window_end": reference.get("window_end"),
            "bin_edges": config["bin_edges"], "psi": None, "severity": None, **compared}
    for role, report in (("baseline", reference), ("current", current or {})):
        for name in ("total_count", "valid_count", "excluded_count", "bin_counts"):
            body[f"{role}_{name}"] = report.get(name)
    identity = ["drift-v1", config["config_id"], node_id, body["baseline_id"],
                body["current_report_id"], (policy or {}).get("policy_id"), body["state"]]
    return dict(body, event_id=sha(identity), evaluated_at=now.isoformat())


def _alerts(state: dict, event: dict, now: datetime) -> None:
    key = (event["config_id"], event["node_id"])
    if event["state"] == "ready" and event["severity"] == "stable":
        for alert in state["drift_alerts"].values():
            if (alert["config_id"], alert["node_id"]) == key and alert["status"] != "resolved":
                alert.update(status="resolved", resolved_at=now.isoformat(),
                             resolved_by_event_id=event["event_id"])
        return
    if event["state"] in ("unconfigured", "missing_baseline", "missing_current"):
        return
    identity = sha(["drift-alert-v1", event["event_id"]])
    if identity in state["drift_alerts"]:
        return  # 같은 관측 재전달/재평가는 확인 상태를 초기화하지 않는다.
    state["drift_alerts"][identity] = {
        "alert_id": identity, "event_id": event["event_id"], "config_id": key[0], "node_id": key[1],
        "model_name": event["model_name"], "version": event["version"], "feature": event["feature"],
        "policy_id": event["policy"]["policy_id"], "policy_version": event["policy"]["policy_version"],
        "severity": event["severity"] or "warning", "cause": event["state"], "psi": event["psi"],
        "message": event["reason"], "status": "open", "triggered_at": event["evaluated_at"],
        "acked_at": None, "resolved_at": None, "resolved_by_event_id": None,
    }


def refresh_scope(state: dict, config_id: str, node_id: str, *, now: datetime | None = None) -> dict:
    """호출자의 원자 저장에 참여한다. 별도 I/O나 자동 재학습은 수행하지 않는다."""
    now = now or _now()
    config, policy, baseline, current = _context(state, config_id, node_id)
    key = _scope(config_id, node_id)
    basis_hash = sha([(baseline or {}).get("baseline_id"), (policy or {}).get("policy_id")])
    basis = state["drift_basis"].get(key)
    if basis is None or basis["hash"] != basis_hash:
        basis = {"hash": basis_hash, "revision": basis["revision"] + 1 if basis else 1}
        state["drift_basis"][key] = basis
    event = _observation(config, node_id, policy, baseline, current, now)
    # 기준 A→B→A에서도 새 선택 회차를 고정해 과거 경고 상태와 구분한다.
    event["basis_revision"] = basis["revision"]
    event["event_id"] = sha([event["event_id"], basis["revision"]])
    previous = state["drift_events"].get(event["event_id"])
    if previous is None:
        state["drift_events"][event["event_id"]] = event
    else:
        event = previous
    state["drift_current"][key] = event["event_id"]
    _alerts(state, event, now)
    return event


def put_policy(body: dict) -> dict:
    value = DistributionPolicyRequest(**body).model_dump()
    config_id = value["config_id"]
    with ledger._lock:
        state = ledger._load()
        config = ledger._required(state, "configs", config_id)
        previous = state["drift_policies"].get(state["drift_policy_current"].get(config_id, ""))
        if previous and all(previous[k] == v for k, v in value.items()):
            return previous
        version = previous["policy_version"] + 1 if previous else 1
        policy = dict(value, policy_version=version, policy_id=sha(["policy-v1", version, value]),
                      created_at=_now().isoformat(), resolution="next_valid_stable")
        state["drift_policies"][policy["policy_id"]] = policy
        state["drift_policy_current"][config_id] = policy["policy_id"]
        for node in config["node_ids"]:
            refresh_scope(state, config_id, node)
        ledger._save(state)
        return policy


def overview() -> dict:
    with ledger._lock:
        state = ledger._load()
        before = sha(state)
        items = [refresh_scope(state, config["config_id"], node)
                 for config in state["configs"].values() for node in config["node_ids"]]
        if sha(state) != before:
            ledger._save(state)
        alerts = sorted(state["drift_alerts"].values(), key=lambda a: (a["triggered_at"], a["alert_id"]), reverse=True)
        return {"configs": list(state["configs"].values()), "items": items, "alerts": alerts}


def events(config_id: str, node_id: str) -> list[dict]:
    with ledger._lock:
        state = ledger._load()
        _context(state, config_id, node_id)
        return [event for event in state["drift_events"].values()
                if event["config_id"] == config_id and event["node_id"] == node_id]


def ack(alert_id: str) -> dict:
    with ledger._lock:
        state = ledger._load()
        alert = ledger._required(state, "drift_alerts", alert_id)
        if alert["status"] == "open":
            alert.update(status="acked", acked_at=_now().isoformat())
            ledger._save(state)
        return alert
