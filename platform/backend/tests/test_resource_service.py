"""리소스 모니터링 서비스 + Batch 자원 게이트 통합 테스트"""
from __future__ import annotations

import pytest

from config.server_manager import save_servers
from models.federated_schemas import SiloGroupRequest, TrainingJobRequest
from models.packaging_schemas import ModelRegisterRequest
from models.resource_schemas import ResourceLimit, ResourceSample
from services import (
    model_registry,
    resource_service,
    silo_group_service,
    training_job_service,
)


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
        SiloGroupRequest(group_id="g1", member_node_ids=["silo-1", "silo-2"])
    )


def _sample(
    silo_id: str,
    cpu: float = 10.0,
    mem: float = 10.0,
    *,
    gpu: float | None = None,
    disk: float | None = None,
    ts: str = "2026-05-14T00:00:00Z",
) -> ResourceSample:
    return ResourceSample(
        silo_id=silo_id,
        cpu_pct=cpu,
        mem_pct=mem,
        gpu_pct=gpu,
        disk_pct=disk,
        timestamp=ts,
    )


@pytest.mark.unit
def test_set_get_delete_limit():
    limit = ResourceLimit(silo_id="silo-1", cpu_pct_max=80.0, mem_pct_max=90.0)
    resource_service.set_limit(limit)

    got = resource_service.get_limit("silo-1")
    assert got is not None
    assert got.cpu_pct_max == 80.0

    resource_service.delete_limit("silo-1")
    assert resource_service.get_limit("silo-1") is None


@pytest.mark.unit
def test_ingest_sample_below_limit_does_not_trigger_alert():
    resource_service.set_limit(ResourceLimit(silo_id="silo-1", cpu_pct_max=80.0))

    result = resource_service.ingest_sample(_sample("silo-1", cpu=10.0))

    assert result["alerts"] == []
    alerts, total = resource_service.list_alerts()
    assert total == 0
    assert alerts == []


@pytest.mark.unit
def test_ingest_sample_above_limit_emits_alert():
    resource_service.set_limit(
        ResourceLimit(silo_id="silo-1", cpu_pct_max=80.0, mem_pct_max=90.0)
    )

    result = resource_service.ingest_sample(_sample("silo-1", cpu=95.0, mem=50.0))

    assert len(result["alerts"]) == 1
    alerts, total = resource_service.list_alerts()
    assert total == 1
    assert len(alerts) == 1
    assert alerts[0].metric == "cpu"
    assert alerts[0].observed == 95.0


@pytest.mark.unit
def test_multiple_metrics_can_trigger_simultaneously():
    resource_service.set_limit(
        ResourceLimit(
            silo_id="silo-1",
            cpu_pct_max=50.0,
            mem_pct_max=50.0,
            gpu_pct_max=50.0,
        )
    )

    resource_service.ingest_sample(_sample("silo-1", cpu=80.0, mem=80.0, gpu=80.0))

    alerts, _ = resource_service.list_alerts()
    metrics = {a.metric for a in alerts}
    assert metrics == {"cpu", "mem", "gpu"}


@pytest.mark.unit
def test_no_limit_means_no_alert():
    resource_service.ingest_sample(_sample("silo-1", cpu=99.0, mem=99.0))
    alerts, total = resource_service.list_alerts()
    assert total == 0
    assert alerts == []


@pytest.mark.unit
def test_is_silo_available_returns_true_when_no_data():
    assert resource_service.is_silo_available("silo-99") is True


@pytest.mark.unit
def test_is_silo_available_false_when_over_budget():
    resource_service.set_limit(ResourceLimit(silo_id="silo-1", cpu_pct_max=80.0))
    resource_service.ingest_sample(_sample("silo-1", cpu=85.0))
    assert resource_service.is_silo_available("silo-1") is False


@pytest.mark.unit
def test_usage_summary_includes_over_budget_flag():
    resource_service.set_limit(ResourceLimit(silo_id="silo-1", cpu_pct_max=80.0))
    resource_service.ingest_sample(_sample("silo-1", cpu=85.0, mem=10.0))
    resource_service.ingest_sample(_sample("silo-2", cpu=10.0, mem=10.0))

    summary = {s.silo_id: s for s in resource_service.usage_summary()}

    assert summary["silo-1"].over_budget is True
    assert summary["silo-2"].over_budget is False


@pytest.mark.unit
def test_batch_tick_holds_when_group_under_pressure():
    """그룹 멤버 한 노드라도 자원 압박 시 잡이 라운드를 열지 않아야 한다."""
    training_job_service.create_job(
        TrainingJobRequest(
            job_id="j1",
            model_name="alpha",
            version="1.0.0",
            group_id="g1",
            schedule_kind="chain",
            min_contributions=2,
            max_rounds=3,
        )
    )
    resource_service.set_limit(ResourceLimit(silo_id="silo-1", cpu_pct_max=80.0))
    resource_service.ingest_sample(_sample("silo-1", cpu=95.0))

    triggered = training_job_service.tick()

    assert triggered == []
    job = training_job_service.get_job("j1")
    assert job.current_round_id is None


@pytest.mark.unit
def test_batch_tick_proceeds_after_pressure_relieved():
    training_job_service.create_job(
        TrainingJobRequest(
            job_id="j1",
            model_name="alpha",
            version="1.0.0",
            group_id="g1",
            schedule_kind="chain",
            min_contributions=2,
            max_rounds=3,
        )
    )
    resource_service.set_limit(ResourceLimit(silo_id="silo-1", cpu_pct_max=80.0))
    resource_service.ingest_sample(_sample("silo-1", cpu=95.0))
    assert training_job_service.tick() == []

    # 다음 샘플은 정상 범위
    resource_service.ingest_sample(_sample("silo-1", cpu=10.0))
    triggered = training_job_service.tick()

    assert triggered == ["j1"]
