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

    클러스터 c1(집계자 silo-1): silo-3 30샘플 [2.0, 6.0], silo-4 10샘플 [10.0, 2.0]
      엣지 = (30/40)·[2,6] + (10/40)·[10,2] = [1.5+2.5, 4.5+0.5] = [4.0, 5.0], N_c=40
    루트: silo-1 대리 40샘플 [4.0, 5.0], silo-2 60샘플 [1.0, 0.0]
      글로벌 = (40/100)·[4,5] + (60/100)·[1,0] = [1.6+0.6, 2.0+0.0] = [2.2, 2.0]
    """
    _make_cluster("c1", "silo-1", ["silo-3", "silo-4"])
    rnd = _create_round(min_contrib=2)

    cluster_total, combined = edge.combine(
        [("silo-3", 30, [2.0, 6.0]), ("silo-4", 10, [10.0, 2.0])]
    )
    assert cluster_total == 40
    assert combined == pytest.approx([4.0, 5.0])

    record = _contribute(
        rnd.round_id,
        "silo-1",
        cluster_total,
        combined,
        aggregated_from=["silo-3", "silo-4"],
    )
    _contribute(rnd.round_id, "silo-2", 60, [1.0, 0.0])

    assert record.aggregated_from == ["silo-3", "silo-4"]
    assert record.sample_count == 40

    result = training_round_service.aggregate_round(rnd.round_id)

    assert result.contributor_count == 2
    assert result.total_samples == 100
    assert result.parameters[0] == pytest.approx(2.2)
    assert result.parameters[1] == pytest.approx(2.0)


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
