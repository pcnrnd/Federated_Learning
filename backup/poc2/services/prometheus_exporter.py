"""Prometheus text exposition format 익스포트

외부 의존성 없이 Prometheus가 직접 스크랩 가능한 텍스트를 생성한다.
Grafana 대시보드는 이 엔드포인트를 Prometheus 데이터 소스로 사용한다.
"""
from __future__ import annotations

from services import metric_store


_HELP: dict[str, str] = {
    "accuracy": "모델 정확도 (사일로 보고)",
    "latency_ms": "모델 추론 지연 (ms)",
    "throughput_rps": "모델 처리량 (요청/초)",
}


def render() -> str:
    """현재 보유 메트릭을 Prometheus exposition 텍스트로 직렬화"""
    lines: list[str] = []
    rendered_metrics: set[str] = set()

    samples, _ = metric_store.query()
    for sample in samples:
        metric = sample.metric
        if metric not in rendered_metrics:
            help_text = _HELP.get(metric, metric)
            lines.append(f"# HELP fed_model_{metric} {help_text}")
            lines.append(f"# TYPE fed_model_{metric} gauge")
            rendered_metrics.add(metric)
        labels = (
            f'model="{sample.model_name}",'
            f'version="{sample.version}",'
            f'node="{sample.node_id}"'
        )
        lines.append(f"fed_model_{metric}{{{labels}}} {sample.value}")

    return "\n".join(lines) + ("\n" if lines else "")
