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
