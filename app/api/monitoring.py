"""모니터링 API 엔드포인트

엔드포인트 분류:
  * 수집: POST /metrics, POST /distribution
  * 조회: GET /metrics, GET /summary, GET /audit, GET /retrain-triggers
  * 드리프트: POST /baselines, POST /drift
  * 알림 규칙: POST/GET/DELETE /rules
  * 알림 인스턴스: GET /alerts, POST /alerts/{id}/ack
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from models.common_schemas import (
    AuditEvent,
    IngestResponse,
    MetricAggregateStats,
    MetricsSummaryResponse,
    OkResponse,
    PaginatedResponse,
)
from models.monitoring_schemas import (
    Alert,
    AlertRule,
    BaselineRequest,
    DistributionStats,
    DriftReport,
    MetricIngest,
    MetricSample,
    RetrainTrigger,
)
from services import (
    alert_service,
    audit_logger,
    drift_detector,
    metric_store,
    prometheus_exporter,
)

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.post("/metrics", status_code=202, response_model=IngestResponse)
def ingest_metric(sample: MetricIngest) -> IngestResponse:
    """사일로에서 성능 메트릭 단일 샘플을 보고한다."""
    metric_store.ingest(sample)
    triggered = alert_service.evaluate_metric(
        MetricSample(
            node_id=sample.node_id,
            model_name=sample.model_name,
            version=sample.version,
            metric=sample.metric,
            value=sample.value,
            timestamp=sample.timestamp,
        )
    )
    return IngestResponse(ok=True, alerts=[a.alert_id for a in triggered])


@router.get("/metrics", response_model=PaginatedResponse[MetricSample])
def query_metrics(
    model_name: str | None = Query(default=None),
    version: str | None = Query(default=None),
    node_id: str | None = Query(default=None),
    metric: str | None = Query(default=None),
    start_time: str | None = Query(default=None, description="ISO-8601 하한"),
    end_time: str | None = Query(default=None, description="ISO-8601 상한"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=10000),
) -> PaginatedResponse[MetricSample]:
    """필터·시간 범위·페이지네이션으로 메트릭 샘플을 조회한다."""
    items, total = metric_store.query(
        model_name=model_name,
        version=version,
        node_id=node_id,
        metric=metric,
        start_time=start_time,
        end_time=end_time,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/summary", response_model=MetricsSummaryResponse)
def metrics_summary(model_name: str, version: str) -> MetricsSummaryResponse:
    """주요 성능 지표 3종 집계 요약 (DoD: 실시간 수집)"""
    return MetricsSummaryResponse(
        accuracy=MetricAggregateStats(
            **metric_store.aggregate(model_name=model_name, version=version, metric="accuracy")
        ),
        latency_ms=MetricAggregateStats(
            **metric_store.aggregate(
                model_name=model_name, version=version, metric="latency_ms"
            )
        ),
        throughput_rps=MetricAggregateStats(
            **metric_store.aggregate(
                model_name=model_name, version=version, metric="throughput_rps"
            )
        ),
    )


@router.post("/baselines", status_code=201, response_model=OkResponse)
def set_baseline_endpoint(request: BaselineRequest) -> OkResponse:
    drift_detector.set_baseline(request)
    return OkResponse(ok=True)


@router.post("/drift", response_model=DriftReport)
def evaluate_drift_endpoint(stats: DistributionStats) -> DriftReport:
    """현재 분포를 받아 드리프트를 계산하고 알림/재교육 트리거를 평가한다."""
    report = drift_detector.detect_drift(stats)
    alerts, retrain = alert_service.evaluate_drift(report)
    _ = (alerts, retrain)  # 부수 효과(저장/감사로그)만 필요
    return report


@router.post("/rules", response_model=AlertRule, status_code=201)
def upsert_rule_endpoint(rule: AlertRule) -> AlertRule:
    return alert_service.upsert_rule(rule)


@router.get("/rules", response_model=list[AlertRule])
def list_rules_endpoint() -> list[AlertRule]:
    return alert_service.list_rules()


@router.delete("/rules/{rule_id}", response_model=OkResponse)
def delete_rule_endpoint(rule_id: str) -> OkResponse:
    alert_service.delete_rule(rule_id)
    return OkResponse(ok=True)


@router.get("/alerts", response_model=PaginatedResponse[Alert])
def list_alerts_endpoint(
    status: str | None = Query(default=None),
    model_name: str | None = Query(default=None),
    metric: str | None = Query(default=None),
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> PaginatedResponse[Alert]:
    """알림 인스턴스를 필터·페이지네이션으로 조회한다."""
    items, total = alert_service.list_alerts(
        status=status,
        model_name=model_name,
        metric=metric,
        start_time=start_time,
        end_time=end_time,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.post("/alerts/{alert_id}/ack", response_model=Alert)
def ack_alert_endpoint(alert_id: str) -> Alert:
    return alert_service.ack_alert(alert_id)


@router.get("/audit", response_model=list[AuditEvent])
def audit_tail_endpoint(tail: int = Query(default=100, ge=1, le=10000)) -> list[AuditEvent]:
    """감사 로그 tail — 구조화된 AuditEvent 목록"""
    raw = audit_logger.tail(tail)
    events: list[AuditEvent] = []
    for row in raw:
        data = dict(row)
        event_name = str(data.pop("event", "unknown"))
        ts = data.pop("ts", None) or data.pop("timestamp", None)
        if ts is not None:
            ts = str(ts)
        events.append(AuditEvent(event=event_name, timestamp=ts, extra=data))
    return events


@router.get("/retrain-triggers", response_model=list[RetrainTrigger])
def retrain_triggers_endpoint(
    model_name: str | None = Query(default=None),
) -> list[RetrainTrigger]:
    """감사 로그에서 retrain_trigger 이벤트를 RetrainTrigger로 변환"""
    events = alert_service.latest_retrain_triggers(model_name=model_name)
    return [
        RetrainTrigger(
            model_name=str(e.get("model", "")),
            version=str(e.get("version", "")),
            reason=f"PSI critical on feature '{e.get('feature', '')}'",
            triggered_at=str(e.get("timestamp", "")),
        )
        for e in events
    ]


@router.get("/prometheus", response_class=PlainTextResponse)
def prometheus_endpoint() -> str:
    """Prometheus exposition format. Grafana 데이터 소스 연결용."""
    return prometheus_exporter.render()
