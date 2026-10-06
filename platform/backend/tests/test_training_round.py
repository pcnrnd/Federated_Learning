"""학습 라운드 + 파라미터 수집 통합 테스트"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from config.federated_manager import load_training_rounds, save_training_rounds
from config.server_manager import save_servers
from models.federated_schemas import (
    ParameterContribution,
    SiloGroupRequest,
    TrainingRoundCreate,
)
from models.packaging_schemas import ModelRegisterRequest
from services import (
    fedavg_aggregator,
    model_registry,
    silo_group_service,
    training_round_service,
)
from silo_sdk import edge


@pytest.fixture(autouse=True)
def _seed(tmp_path):
    save_servers(
        {
            "silo-1": {
                "base_url": "tcp://localhost:2371",
                "label": "silo-1",
                "type": "remote",
                "role": "client",
                "tls": False,
            },
            "silo-2": {
                "base_url": "tcp://localhost:2372",
                "label": "silo-2",
                "type": "remote",
                "role": "client",
                "tls": False,
            },
            "silo-3": {
                "base_url": "tcp://localhost:2373",
                "label": "silo-3",
                "type": "remote",
                "role": "client",
                "tls": False,
            },
            "silo-4": {
                "base_url": "tcp://localhost:2374",
                "label": "silo-4",
                "type": "remote",
                "role": "client",
                "tls": False,
            },
        }
    )
    weights = tmp_path / "m.pt"
    weights.write_bytes(b"")
    model_registry.register_model(
        ModelRegisterRequest(
            name="alpha",
            version="1.0.0",
            framework="pytorch",
            weights_path=str(weights),
        )
    )
    silo_group_service.create_group(
        SiloGroupRequest(
            group_id="g1",
            description="test",
            member_node_ids=["silo-1", "silo-2"],
        )
    )


def _create_round(min_contrib: int = 2):
    return training_round_service.create_round(
        TrainingRoundCreate(
            model_name="alpha",
            version="1.0.0",
            group_id="g1",
            min_contributions=min_contrib,
        )
    )


def _contribute(
    round_id: str,
    silo_id: str,
    samples: int,
    params: list[float],
    aggregated_from: list[str] | None = None,
):
    return training_round_service.submit_contribution(
        ParameterContribution(
            round_id=round_id,
            silo_id=silo_id,
            sample_count=samples,
            parameters=params,
            aggregated_from=aggregated_from or [],
        )
    )


@pytest.mark.unit
def test_create_round_validates_model_and_group():
    with pytest.raises(HTTPException) as exc:
        training_round_service.create_round(
            TrainingRoundCreate(
                model_name="ghost",
                version="1.0.0",
                group_id="g1",
            )
        )
    assert exc.value.status_code == 404


@pytest.mark.unit
def test_create_round_validates_group():
    with pytest.raises(HTTPException) as exc:
        training_round_service.create_round(
            TrainingRoundCreate(
                model_name="alpha",
                version="1.0.0",
                group_id="missing",
            )
        )
    assert exc.value.status_code == 404


@pytest.mark.unit
def test_contribution_must_be_group_member():
    rnd = _create_round()
    with pytest.raises(HTTPException) as exc:
        _contribute(rnd.round_id, "silo-99", 10, [1.0])
    assert exc.value.status_code == 403


@pytest.mark.unit
def test_duplicate_contribution_rejected():
    rnd = _create_round()
    _contribute(rnd.round_id, "silo-1", 10, [1.0])
    with pytest.raises(HTTPException) as exc:
        _contribute(rnd.round_id, "silo-1", 10, [1.0])
    assert exc.value.status_code == 409


@pytest.mark.unit
def test_aggregate_below_min_contrib_returns_400():
    rnd = _create_round(min_contrib=2)
    _contribute(rnd.round_id, "silo-1", 10, [1.0])
    with pytest.raises(HTTPException) as exc:
        training_round_service.aggregate_round(rnd.round_id)
    assert exc.value.status_code == 400


@pytest.mark.unit
def test_full_round_lifecycle_aggregates_weighted_fedavg():
    rnd = _create_round(min_contrib=2)
    _contribute(rnd.round_id, "silo-1", 90, [10.0, 10.0])
    _contribute(rnd.round_id, "silo-2", 10, [0.0, 0.0])

    result = training_round_service.aggregate_round(rnd.round_id)

    assert result.contributor_count == 2
    assert result.total_samples == 100
    assert result.parameter_dim == 2
    assert result.parameters[0] == pytest.approx(9.0)
    assert result.parameters[1] == pytest.approx(9.0)

    completed = training_round_service.get_round(rnd.round_id)
    assert completed.status == "completed"
    assert completed.aggregated_at is not None


@pytest.mark.unit
def test_contribution_after_completion_rejected():
    rnd = _create_round(min_contrib=2)
    _contribute(rnd.round_id, "silo-1", 1, [1.0])
    _contribute(rnd.round_id, "silo-2", 1, [3.0])
    training_round_service.aggregate_round(rnd.round_id)

    with pytest.raises(HTTPException) as exc:
        training_round_service.submit_contribution(
            ParameterContribution(
                round_id=rnd.round_id,
                silo_id="silo-1",
                sample_count=1,
                parameters=[1.0],
            )
        )
    assert exc.value.status_code in (409, 403)  # 상태 또는 그룹 검증


# ---------- 멤버십 스냅샷 (HFL 설계 스펙 §4.2 / §5) ----------


def _make_cluster(group_id: str, aggregator: str, members: list[str]):
    return silo_group_service.create_group(
        SiloGroupRequest(
            group_id=group_id,
            member_node_ids=members,
            aggregator_node_id=aggregator,
        )
    )


@pytest.mark.unit
def test_create_round_freezes_member_snapshot():
    rnd = _create_round()

    assert rnd.member_snapshot == ["silo-1", "silo-2"]


@pytest.mark.unit
def test_create_round_records_cluster_snapshot():
    """스냅샷 안 집계자의 클러스터 멤버를 생성 시점 그대로 기록한다 — 이후 클러스터 변경 무영향"""
    _make_cluster("edge-a", "silo-2", ["silo-3", "silo-4"])

    rnd = _create_round()
    silo_group_service.update_group(
        "edge-a",
        SiloGroupRequest(group_id="edge-a", member_node_ids=["silo-3"], aggregator_node_id="silo-2"),
    )

    assert rnd.cluster_snapshot == {"silo-2": ["silo-3", "silo-4"]}
    stored = training_round_service.get_round(rnd.round_id)
    assert stored.cluster_snapshot == {"silo-2": ["silo-3", "silo-4"]}


@pytest.mark.unit
def test_create_round_without_aggregator_records_empty_cluster_snapshot():
    """집계자가 없으면 {} — 스냅샷 없는 이전 레코드(None)와 구분된다"""
    assert _create_round().cluster_snapshot == {}


@pytest.mark.unit
def test_cluster_snapshot_round_trips_through_sqlite(monkeypatch, tmp_path):
    from storage.factory import reset_repositories

    monkeypatch.setenv("FED_STORAGE", "sqlite")
    reset_repositories()
    weights = tmp_path / "s.pt"
    weights.write_bytes(b"")
    model_registry.register_model(
        ModelRegisterRequest(
            name="alpha", version="1.0.0", framework="pytorch", weights_path=str(weights)
        )
    )
    silo_group_service.create_group(
        SiloGroupRequest(group_id="g1", member_node_ids=["silo-1", "silo-2"])
    )
    _make_cluster("edge-a", "silo-2", ["silo-3"])
    rnd = _create_round()

    reset_repositories()  # 저장소를 새로 연다

    stored = training_round_service.get_round(rnd.round_id)
    assert stored.cluster_snapshot == {"silo-2": ["silo-3"]}
    assert load_training_rounds()[rnd.round_id]["cluster_snapshot"] == {"silo-2": ["silo-3"]}


@pytest.mark.unit
def test_node_added_mid_round_is_rejected_by_snapshot():
    """라운드 open 후 그룹에 추가된 노드는 진행 중 라운드에 기여할 수 없다 (403)"""
    rnd = _create_round()
    silo_group_service.update_group(
        "g1",
        SiloGroupRequest(
            group_id="g1", member_node_ids=["silo-1", "silo-2", "silo-3"]
        ),
    )

    with pytest.raises(HTTPException) as exc:
        _contribute(rnd.round_id, "silo-3", 10, [1.0])

    assert exc.value.status_code == 403


@pytest.mark.unit
def test_node_removed_mid_round_can_still_contribute():
    """스냅샷 기준이므로 라운드 도중 그룹에서 빠져도 진행 중 라운드엔 무영향"""
    rnd = _create_round()
    silo_group_service.update_group(
        "g1", SiloGroupRequest(group_id="g1", member_node_ids=["silo-1"])
    )

    record = _contribute(rnd.round_id, "silo-2", 10, [1.0])

    assert record.silo_id == "silo-2"


@pytest.mark.unit
def test_legacy_round_without_snapshot_falls_back_to_current_group():
    """스냅샷 필드가 없는 기존 레코드는 현재 그룹 멤버십으로 검증한다 (하위 호환)"""
    rnd = _create_round()
    rounds = load_training_rounds()
    legacy = dict(rounds[rnd.round_id])
    legacy.pop("member_snapshot", None)
    rounds[rnd.round_id] = legacy
    save_training_rounds(rounds)

    record = _contribute(rnd.round_id, "silo-1", 10, [1.0])

    assert record.silo_id == "silo-1"


# ---------- 대리 제출 provenance 검증 (HFL 설계 스펙 §4.2 / §5) ----------


@pytest.mark.unit
def test_flat_submission_keeps_empty_aggregated_from():
    """평면 제출은 기존 경로와 완전히 동일 — aggregated_from 빈 목록"""
    rnd = _create_round()

    record = _contribute(rnd.round_id, "silo-1", 10, [1.0])

    assert record.aggregated_from == []


@pytest.mark.unit
def test_aggregated_from_by_non_aggregator_rejected_403():
    """클러스터 집계자가 아닌 노드가 대리 제출하면 403"""
    rnd = _create_round()

    with pytest.raises(HTTPException) as exc:
        _contribute(rnd.round_id, "silo-2", 10, [1.0], aggregated_from=["silo-3"])

    assert exc.value.status_code == 403


@pytest.mark.unit
def test_aggregated_from_outside_cluster_rejected_422():
    """목록이 클러스터 멤버의 부분집합이 아니면 422"""
    _make_cluster("c1", "silo-1", ["silo-3"])
    rnd = _create_round()

    with pytest.raises(HTTPException) as exc:
        _contribute(
            rnd.round_id, "silo-1", 10, [1.0], aggregated_from=["silo-3", "silo-4"]
        )

    assert exc.value.status_code == 422
    assert "silo-4" in exc.value.detail


@pytest.mark.unit
def test_aggregator_including_itself_rejected_422():
    """집계자가 자기 자신을 하위 목록에 넣으면 422"""
    _make_cluster("c1", "silo-1", ["silo-3", "silo-4"])
    rnd = _create_round()

    with pytest.raises(HTTPException) as exc:
        _contribute(
            rnd.round_id, "silo-1", 10, [1.0], aggregated_from=["silo-1", "silo-3"]
        )

    assert exc.value.status_code == 422


@pytest.mark.unit
def test_cluster_member_cannot_contribute_directly():
    """클러스터 멤버는 루트 그룹 스냅샷에 없으므로 직접 기여가 자동 차단된다 (403)"""
    _make_cluster("c1", "silo-1", ["silo-3", "silo-4"])
    rnd = _create_round()

    with pytest.raises(HTTPException) as exc:
        _contribute(rnd.round_id, "silo-3", 10, [1.0])

    assert exc.value.status_code == 403


@pytest.mark.unit
def test_proxy_submission_end_to_end_matches_hand_calculation():
    """집계자 대리 제출 E2E — 엣지 집계 후 글로벌 집계 결과를 손계산과 대조.

    집계자 silo-1도 **자기 로컬 데이터를 가진 사일로**이므로 자신의 기여가 엣지
    참여 목록에 들어간다 (2026-07-24-silo-hierarchy-design.md §엣지 집계의 참여 범위).

    클러스터 c1(집계자 silo-1 자신 40샘플 [1.0, 1.0]):
      하위 silo-3 30샘플 [2.0, 6.0], silo-4 10샘플 [10.0, 2.0]
      엣지 = (40/80)·[1,1] + (30/80)·[2,6] + (10/80)·[10,2] = [2.5, 3.0], N_c=80
    루트: silo-1 대리 80샘플 [2.5, 3.0], silo-2 20샘플 [1.0, 0.0]
      글로벌 = (80/100)·[2.5,3] + (20/100)·[1,0] = [2.0+0.2, 2.4+0.0] = [2.2, 2.4]

    provenance는 하위만 — `aggregated_from`에 자기 자신을 넣으면 422다(계약 유지).
    """
    _make_cluster("c1", "silo-1", ["silo-3", "silo-4"])
    rnd = _create_round(min_contrib=2)

    cluster_total, combined = edge.combine(
        [
            ("silo-1", 40, [1.0, 1.0]),  # 집계자 자신의 로컬 학습
            ("silo-3", 30, [2.0, 6.0]),
            ("silo-4", 10, [10.0, 2.0]),
        ]
    )
    assert cluster_total == 80
    assert combined == pytest.approx([2.5, 3.0])

    record = _contribute(
        rnd.round_id,
        "silo-1",
        cluster_total,
        combined,
        aggregated_from=["silo-3", "silo-4"],
    )
    _contribute(rnd.round_id, "silo-2", 20, [1.0, 0.0])

    assert record.aggregated_from == ["silo-3", "silo-4"]
    assert record.sample_count == 80

    result = training_round_service.aggregate_round(rnd.round_id)

    assert result.contributor_count == 2
    assert result.total_samples == 100
    assert result.parameters[0] == pytest.approx(2.2)
    assert result.parameters[1] == pytest.approx(2.4)

    # 평면 등가 — 같은 4개 사일로를 평면 제출했을 때와 수치가 일치한다
    flat_params, flat_total = fedavg_aggregator.aggregate(
        [
            ("silo-1", 40, [1.0, 1.0]),
            ("silo-3", 30, [2.0, 6.0]),
            ("silo-4", 10, [10.0, 2.0]),
            ("silo-2", 20, [1.0, 0.0]),
        ]
    )
    assert flat_total == result.total_samples
    assert result.parameters == pytest.approx(flat_params)


@pytest.mark.unit
def test_empty_group_snapshot_does_not_fall_back_to_current_group():
    """MEDIUM-4 — 멤버 0명 그룹의 스냅샷 []은 레거시(None)와 구분되어 폴백하지 않는다.

    폴백하면 라운드 도중 추가된 노드가 기여할 수 있어 스냅샷 규칙이 이 경로에서만 깨진다.
    """
    silo_group_service.create_group(
        SiloGroupRequest(group_id="empty", member_node_ids=[])
    )
    rnd = training_round_service.create_round(
        TrainingRoundCreate(model_name="alpha", version="1.0.0", group_id="empty")
    )
    assert rnd.member_snapshot == []

    silo_group_service.update_group(
        "empty", SiloGroupRequest(group_id="empty", member_node_ids=["silo-1"])
    )

    with pytest.raises(HTTPException) as exc:
        _contribute(rnd.round_id, "silo-1", 10, [1.0])

    assert exc.value.status_code == 403


@pytest.mark.unit
def test_aggregated_from_with_duplicates_rejected_422():
    """LOW-5 — 중복 원소는 리니지를 왜곡하므로 거부한다"""
    _make_cluster("c1", "silo-1", ["silo-3", "silo-4"])
    rnd = _create_round()

    with pytest.raises(HTTPException) as exc:
        _contribute(
            rnd.round_id, "silo-1", 30, [1.0], aggregated_from=["silo-3", "silo-3"]
        )

    assert exc.value.status_code == 422
    assert "중복" in exc.value.detail


@pytest.mark.unit
def test_double_counting_topology_is_unbuildable():
    """HIGH-2 — 리뷰의 이중 계상 시나리오는 그룹 생성 단계에서 막혀 라운드에 도달하지 못한다.

    리뷰 재현: root[silo-1,2,3] + c1(agg=silo-1, members=[silo-3,4]) 이면
    silo-1의 대리 제출(silo-3 표본 포함)과 silo-3의 직접 제출이 겹쳐
    total_samples가 100 대신 130이 되고 글로벌 파라미터가 조용히 오염됐다.
    """
    silo_group_service.update_group(
        "g1",
        SiloGroupRequest(
            group_id="g1", member_node_ids=["silo-1", "silo-2", "silo-3"]
        ),
    )

    with pytest.raises(HTTPException) as exc:
        _make_cluster("c1", "silo-1", ["silo-3", "silo-4"])

    assert exc.value.status_code == 400
    assert "이중 계상" in exc.value.detail


@pytest.mark.unit
def test_proxy_submission_provenance_survives_listing():
    """리니지 조회에도 하위 목록이 보존된다"""
    _make_cluster("c1", "silo-1", ["silo-3", "silo-4"])
    rnd = _create_round()
    _contribute(rnd.round_id, "silo-1", 40, [4.0], aggregated_from=["silo-3"])

    records = training_round_service.list_contributions(rnd.round_id)

    assert len(records) == 1
    assert records[0].aggregated_from == ["silo-3"]


@pytest.mark.unit
def test_create_round의_저장은_round_lock으로_직렬화된다():
    """라운드 파일 쓰기 경합 회귀 테스트 — 잠금 없이 쓰면 동시 기여/집계의
    read-modify-write와 겹쳐 방금 만든 라운드가 유실된다 (기여 404 실측)."""
    import threading

    done = threading.Event()

    def _create():
        _create_round()
        done.set()

    with training_round_service._round_lock:
        worker = threading.Thread(target=_create, daemon=True)
        worker.start()
        # 잠금을 쥔 동안에는 저장이 완료되면 안 된다
        assert not done.wait(timeout=0.3), "create_round가 _round_lock 없이 라운드를 저장했다"
    assert done.wait(timeout=3.0), "잠금 해제 후에도 create_round가 완료되지 않았다"


@pytest.mark.unit
def test_동시_라운드_생성과_기여가_라운드를_유실하지_않는다():
    """생성(쓰기)과 기여(쓰기)가 병렬로 반복돼도 생성된 라운드 전부가 저장소에 남는다."""
    import threading

    base = _create_round(min_contrib=2)
    stop = threading.Event()

    def _spam_contributions():
        seq = 0
        while not stop.is_set():
            # 같은 라운드에 서로 다른 silo_id로 기여를 반복 — 라운드 파일 쓰기 유발
            seq += 1
            try:
                _contribute(base.round_id, "silo-1" if seq % 2 else "silo-2", 1, [1.0])
            except HTTPException:
                pass  # 중복 기여 409는 정상 — 쓰기 경합 유발이 목적

    spammer = threading.Thread(target=_spam_contributions, daemon=True)
    spammer.start()
    try:
        created = [_create_round().round_id for _ in range(30)]
    finally:
        stop.set()
        spammer.join(timeout=5.0)

    stored = load_training_rounds()
    missing = [rid for rid in created if rid not in stored]
    assert not missing, f"동시 쓰기로 유실된 라운드: {missing}"
