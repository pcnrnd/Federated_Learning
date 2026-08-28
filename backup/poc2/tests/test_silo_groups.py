"""사일로 그룹 서비스 단위 테스트"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from config.server_manager import save_servers
from models.federated_schemas import SiloGroupRequest
from services import silo_group_service


@pytest.fixture(autouse=True)
def _seed_servers():
    save_servers(
        {
            "main": {
                "base_url": "unix:///var/run/docker.sock",
                "label": "central",
                "type": "local",
                "role": "central",
            },
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


@pytest.mark.unit
def test_create_and_list_group():
    silo_group_service.create_group(
        SiloGroupRequest(
            group_id="hospital-east",
            description="Eastern region hospitals",
            member_node_ids=["silo-1", "silo-2"],
            tags=["hospital", "east"],
        )
    )

    groups = silo_group_service.list_groups()

    assert len(groups) == 1
    assert groups[0].group_id == "hospital-east"
    assert groups[0].member_node_ids == ["silo-1", "silo-2"]


@pytest.mark.unit
def test_create_rejects_unknown_member_nodes():
    with pytest.raises(HTTPException) as exc:
        silo_group_service.create_group(
            SiloGroupRequest(
                group_id="bad",
                member_node_ids=["silo-1", "ghost-silo"],
            )
        )
    assert exc.value.status_code == 400


@pytest.mark.unit
def test_create_duplicate_returns_409():
    silo_group_service.create_group(
        SiloGroupRequest(group_id="g1", member_node_ids=["silo-1"])
    )
    with pytest.raises(HTTPException) as exc:
        silo_group_service.create_group(
            SiloGroupRequest(group_id="g1", member_node_ids=["silo-2"])
        )
    assert exc.value.status_code == 409


@pytest.mark.unit
def test_update_group_replaces_members_and_updates_timestamp():
    created = silo_group_service.create_group(
        SiloGroupRequest(group_id="g1", member_node_ids=["silo-1"])
    )

    updated = silo_group_service.update_group(
        "g1",
        SiloGroupRequest(
            group_id="g1",
            description="updated",
            member_node_ids=["silo-1", "silo-2"],
        ),
    )

    assert updated.description == "updated"
    assert updated.member_node_ids == ["silo-1", "silo-2"]
    assert updated.updated_at >= created.created_at


@pytest.mark.unit
def test_list_members_joins_with_servers_yaml():
    silo_group_service.create_group(
        SiloGroupRequest(group_id="g1", member_node_ids=["silo-1", "silo-2"])
    )

    members = silo_group_service.list_members("g1")

    assert len(members) == 2
    assert members[0].in_servers_yaml is True
    assert members[0].role == "client"


@pytest.mark.unit
def test_delete_group():
    silo_group_service.create_group(
        SiloGroupRequest(group_id="g1", member_node_ids=["silo-1"])
    )

    silo_group_service.delete_group("g1")

    assert silo_group_service.list_groups() == []


# ---------- 엣지 클러스터 (HFL 설계 스펙 §4.2) ----------


def _cluster(group_id: str, aggregator: str, members: list[str]) -> SiloGroupRequest:
    return SiloGroupRequest(
        group_id=group_id,
        member_node_ids=members,
        aggregator_node_id=aggregator,
    )


@pytest.mark.unit
def test_plain_group_has_no_aggregator_by_default():
    """하위 호환 — 기존 요청 형태는 aggregator_node_id 없이 그대로 동작한다."""
    group = silo_group_service.create_group(
        SiloGroupRequest(group_id="g1", member_node_ids=["silo-1"])
    )

    assert group.aggregator_node_id is None


@pytest.mark.unit
def test_create_cluster_records_aggregator():
    cluster = silo_group_service.create_group(
        _cluster("c1", "silo-1", ["silo-3", "silo-4"])
    )

    assert cluster.aggregator_node_id == "silo-1"
    assert cluster.member_node_ids == ["silo-3", "silo-4"]


@pytest.mark.unit
def test_aggregator_cannot_also_be_member():
    """검증 ① 집계자는 클러스터의 상위 — 멤버 겸직 불가"""
    with pytest.raises(HTTPException) as exc:
        silo_group_service.create_group(
            _cluster("c1", "silo-1", ["silo-1", "silo-3"])
        )

    assert exc.value.status_code == 400
    assert "집계자" in exc.value.detail


@pytest.mark.unit
def test_cluster_member_cannot_become_aggregator():
    """검증 ② 2단 제한 — 다른 클러스터의 멤버는 집계자가 될 수 없다"""
    silo_group_service.create_group(_cluster("c1", "silo-1", ["silo-3"]))

    with pytest.raises(HTTPException) as exc:
        silo_group_service.create_group(_cluster("c2", "silo-3", ["silo-4"]))

    assert exc.value.status_code == 400
    assert "2단" in exc.value.detail


@pytest.mark.unit
def test_node_cannot_belong_to_two_clusters():
    """검증 ③ 한 노드는 최대 1개 클러스터의 멤버"""
    silo_group_service.create_group(_cluster("c1", "silo-1", ["silo-3"]))

    with pytest.raises(HTTPException) as exc:
        silo_group_service.create_group(_cluster("c2", "silo-2", ["silo-3"]))

    assert exc.value.status_code == 400
    assert "silo-3" in exc.value.detail


@pytest.mark.unit
def test_unknown_aggregator_node_rejected():
    with pytest.raises(HTTPException) as exc:
        silo_group_service.create_group(_cluster("c1", "ghost", ["silo-3"]))

    assert exc.value.status_code == 400


@pytest.mark.unit
def test_update_group_enforces_cluster_rules():
    """수정 경로에도 동일 검증이 걸린다"""
    silo_group_service.create_group(_cluster("c1", "silo-1", ["silo-3"]))

    with pytest.raises(HTTPException) as exc:
        silo_group_service.update_group(
            "c1", _cluster("c1", "silo-1", ["silo-1", "silo-3"])
        )

    assert exc.value.status_code == 400


@pytest.mark.unit
def test_update_cluster_does_not_collide_with_itself():
    """자기 자신의 기존 멤버십은 중복 소속으로 보지 않는다"""
    silo_group_service.create_group(_cluster("c1", "silo-1", ["silo-3"]))

    updated = silo_group_service.update_group(
        "c1", _cluster("c1", "silo-1", ["silo-3", "silo-4"])
    )

    assert updated.member_node_ids == ["silo-3", "silo-4"]


@pytest.mark.unit
def test_get_cluster_by_aggregator_returns_matching_cluster():
    silo_group_service.create_group(_cluster("c1", "silo-1", ["silo-3", "silo-4"]))

    cluster = silo_group_service.get_cluster_by_aggregator("silo-1")

    assert cluster is not None
    assert cluster.group_id == "c1"
    assert cluster.member_node_ids == ["silo-3", "silo-4"]


@pytest.mark.unit
def test_get_cluster_by_aggregator_returns_none_for_plain_node():
    silo_group_service.create_group(
        SiloGroupRequest(group_id="g1", member_node_ids=["silo-1", "silo-2"])
    )

    assert silo_group_service.get_cluster_by_aggregator("silo-1") is None


# ---------- 리뷰 회귀 (T3 HIGH-1 / HIGH-2 / MEDIUM-3) ----------


@pytest.mark.unit
def test_depth_limit_blocked_regardless_of_creation_order():
    """HIGH-1 재현 — 3단 체인(S2→S1→S3)이 생성 순서와 무관하게 차단된다.

    리뷰 재현 시나리오: c1(agg=silo-1, members=[silo-3])을 **먼저** 만든 뒤
    c2(agg=silo-2, members=[silo-1, ...])를 만들면 silo-1이 집계자이면서 동시에
    c2의 하위가 되어 3단이 된다. 정정 전에는 이 순서만 통과했다.
    """
    silo_group_service.create_group(_cluster("c1", "silo-1", ["silo-3"]))

    with pytest.raises(HTTPException) as exc:
        silo_group_service.create_group(_cluster("c2", "silo-2", ["silo-1", "silo-4"]))

    assert exc.value.status_code == 400
    assert "2단" in exc.value.detail
    assert "silo-1" in exc.value.detail


@pytest.mark.unit
def test_depth_limit_blocked_in_the_reverse_creation_order():
    """HIGH-1 대조군 — 반대 순서(정정 전에도 막히던 방향)도 계속 차단된다."""
    silo_group_service.create_group(_cluster("c2", "silo-2", ["silo-1", "silo-4"]))

    with pytest.raises(HTTPException) as exc:
        silo_group_service.create_group(_cluster("c1", "silo-1", ["silo-3"]))

    assert exc.value.status_code == 400
    assert "2단" in exc.value.detail


@pytest.mark.unit
def test_cluster_cannot_absorb_root_group_member():
    """HIGH-2 재현 — root[silo-1,2,3] + c1(agg=silo-1, members=[silo-3,4])는 이중 계상"""
    silo_group_service.create_group(
        SiloGroupRequest(
            group_id="root", member_node_ids=["silo-1", "silo-2", "silo-3"]
        )
    )

    with pytest.raises(HTTPException) as exc:
        silo_group_service.create_group(_cluster("c1", "silo-1", ["silo-3", "silo-4"]))

    assert exc.value.status_code == 400
    assert "silo-3" in exc.value.detail
    assert "이중 계상" in exc.value.detail


@pytest.mark.unit
def test_root_group_cannot_absorb_cluster_member():
    """HIGH-2 역방향 — 클러스터를 먼저 만들고 루트 그룹이 하위 노드를 흡수하는 경우"""
    silo_group_service.create_group(_cluster("c1", "silo-1", ["silo-3", "silo-4"]))

    with pytest.raises(HTTPException) as exc:
        silo_group_service.create_group(
            SiloGroupRequest(
                group_id="root", member_node_ids=["silo-1", "silo-2", "silo-3"]
            )
        )

    assert exc.value.status_code == 400
    assert "silo-3" in exc.value.detail


@pytest.mark.unit
def test_aggregator_may_be_a_root_group_member():
    """HIGH-2 예외 — 집계자는 루트 그룹 멤버여야 정상이므로 허용된다 (양쪽 순서 모두)"""
    silo_group_service.create_group(_cluster("c1", "silo-1", ["silo-3", "silo-4"]))

    root = silo_group_service.create_group(
        SiloGroupRequest(group_id="root", member_node_ids=["silo-1", "silo-2"])
    )

    assert root.member_node_ids == ["silo-1", "silo-2"]
    assert silo_group_service.get_cluster_by_aggregator("silo-1").group_id == "c1"


@pytest.mark.unit
def test_root_group_member_can_become_an_aggregator():
    """HIGH-2 예외 역순 — 루트 그룹을 먼저 만든 뒤 그 멤버를 집계자로 세울 수 있다"""
    silo_group_service.create_group(
        SiloGroupRequest(group_id="root", member_node_ids=["silo-1", "silo-2"])
    )

    cluster = silo_group_service.create_group(
        _cluster("c1", "silo-1", ["silo-3", "silo-4"])
    )

    assert cluster.aggregator_node_id == "silo-1"


@pytest.mark.unit
def test_node_cannot_aggregate_two_clusters():
    """MEDIUM-3 — 집계자↔클러스터는 1:1"""
    silo_group_service.create_group(_cluster("c1", "silo-1", ["silo-3"]))

    with pytest.raises(HTTPException) as exc:
        silo_group_service.create_group(_cluster("c2", "silo-1", ["silo-4"]))

    assert exc.value.status_code == 400
    assert "이미 클러스터" in exc.value.detail


@pytest.mark.unit
def test_update_root_group_enforces_cluster_exclusivity():
    """수정 경로에서도 루트 그룹이 클러스터 하위를 흡수할 수 없다"""
    silo_group_service.create_group(_cluster("c1", "silo-1", ["silo-3"]))
    silo_group_service.create_group(
        SiloGroupRequest(group_id="root", member_node_ids=["silo-2"])
    )

    with pytest.raises(HTTPException) as exc:
        silo_group_service.update_group(
            "root", SiloGroupRequest(group_id="root", member_node_ids=["silo-2", "silo-3"])
        )

    assert exc.value.status_code == 400
