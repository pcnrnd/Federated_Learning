"""G5-B-F3: completion 창과 수치의 독립 고정 시각 대조. HTTP 실행/성능 실측 시험은 아니다."""
from datetime import datetime, timedelta, timezone

import pytest

from models.serving_schemas import ComparisonGate, RoleObservation, ServingEvent, ServingRoute
from services import serving_requests

ORIGIN = datetime(2026, 1, 1, tzinfo=timezone.utc)


def stamp(seconds):
    return (ORIGIN+timedelta(seconds=seconds)).isoformat()


def event(number, started, completed, *, status="completed", role_status="ok", duration=1500, generation=1, paired=True):
    observation = RoleObservation(deployment_id="p", model_name="m", version="1", status=role_status, duration_ms=duration)
    roles = {role: observation.model_copy(update={"deployment_id": identity})
        for role, identity in (("primary", "p"), ("shadow", "s"))} if status == "completed" else {}
    return ServingEvent(request_id=f"{number:032x}", route_id="route", generation=generation, owner_epoch="test",
        started_at=stamp(started), completed_at=stamp(completed) if completed is not None else None,
        status=status, input_count=1, primary_deployment_id="p", shadow_deployment_id="s", roles=roles,
        paired=paired and status == "completed" and role_status == "ok", difference_count=1,
        mean_abs_difference=2 if paired else None).model_dump()


def ledger(*events):
    route = ServingRoute(route_id="route", primary_deployment_id="p", shadow_deployment_id="s",
        comparison_started_at=stamp(-10), created_at=stamp(-10), changed_at=stamp(-10),
        comparison_gate=ComparisonGate(min_pairs=1, window_seconds=1, max_age_seconds=10,
            max_error_rate=0, max_mean_abs_difference=3))
    return {"routes": {"route": route.model_dump()}, "requests": {entry["request_id"]: entry for entry in events}}


def observe(data, seconds):
    return serving_requests.comparison("route", at=ORIGIN+timedelta(seconds=seconds), data=data)


def test_F3_started_before_window_completed_inside_counts_one_per_second_and_pair_not_missing():
    data = ledger(event(1, 0, 1.5))
    result = observe(data, 1.6)  # (0.6, 1.6], completion1.5 only; start0 is outside.
    assert result.window_start == stamp(.6) and result.window_end == stamp(1.6)
    assert result.request_count == 1 and result.pairs == 1 and result.gate_ready
    for role in ("primary", "shadow"):
        assert result.roles[role].completed_requests == 1
        assert result.roles[role].throughput_rps == pytest.approx(1.0)
        assert result.roles[role].mean_latency_ms == 1500
        assert result.paired_roles[role].throughput_rps == pytest.approx(1.0)
    assert observe(data, 1.6).roles["primary"].completed_requests == 1  # 조회가 카운터를 증가시키지 않는다.


def test_F3_started_inside_but_completed_next_window_only_counts_on_actual_completion():
    data = ledger(event(1, 1.4, 2.1))
    before = observe(data, 1.6)
    assert before.roles["primary"].completed_requests == 0 and before.roles["primary"].throughput_rps == 0
    after = observe(data, 2.2)
    assert after.roles["primary"].completed_requests == 1 and after.roles["primary"].throughput_rps == 1


def test_F3_half_open_completion_boundaries_and_empty_window_have_no_duplicate_or_zero_latency():
    data = ledger(event(1, 0, .6), event(2, .1, 1.6))
    current = observe(data, 1.6)
    assert current.roles["primary"].completed_requests == 1  # 왼쪽 경계 제외, 오른쪽 경계 포함.
    assert current.roles["primary"].throughput_rps == 1
    empty = observe(data, 3)
    assert empty.roles["primary"].completed_requests == 0 and empty.roles["primary"].throughput_rps == 0
    assert empty.roles["primary"].mean_latency_ms is None and not empty.gate_ready


def test_F3_error_completion_counts_but_interruption_and_pending_never_fabricate_completed_latency():
    data = ledger(event(1, 0, 1.5, role_status="error", duration=None, paired=False),
        event(2, -5, 1.4, status="interrupted", paired=False),
        event(3, -5, None, status="pending", paired=False))
    result = observe(data, 1.6)
    assert result.request_count == 3 and result.pending == 1 and result.interrupted == 1
    for role in ("primary", "shadow"):
        value = result.roles[role]
        assert value.requests == 3 and value.completed_requests == 1 and value.errors == 1
        assert value.throughput_rps == 1 and value.measured_requests == 0 and value.mean_latency_ms is None
    assert not result.gate_ready


def test_F3_generation_transition_does_not_recount_old_completions_or_old_pending():
    data = ledger(event(1, 0, 1.5), event(2, -5, None, status="pending", paired=False))
    assert observe(data, 1.6).roles["primary"].completed_requests == 1
    data["routes"]["route"]["generation"] = 2
    switched = observe(data, 1.6)
    assert switched.request_count == 0 and switched.pending == 0 and switched.pairs == 0
    assert switched.roles["primary"].completed_requests == 0 and not switched.gate_ready
