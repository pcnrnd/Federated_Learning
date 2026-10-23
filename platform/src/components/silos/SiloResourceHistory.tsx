import { useEffect } from 'react'
import { demoResourceSamples, groupNodes, useSiloStore } from '@/store/useSiloStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import { resourceHistory } from '@/lib/siloResources'
import { SiloTrendChart } from '@/components/visualization/SiloTrendChart'
import type { ResourceHistoryMetric } from '@/types/simulation'

export function SiloResourceHistory() {
  const demo = useSimulationStore((s) => s.mockEnabled)
  const { silos, selectedHistorySilo, historyMetric, selectHistory, loadHistory, histories, historyErrors } = useSiloStore()
  const nodes = groupNodes(silos, demo)
  const target = nodes.find((s) => s.serverId === selectedHistorySilo)?.serverId ?? nodes[0]?.serverId
  useEffect(() => {
    if (!target || demo) return
    void loadHistory(target)
    const timer = window.setInterval(() => void loadHistory(target), 5000)
    return () => window.clearInterval(timer)
  }, [target, demo, loadHistory])
  if (!target) return null
  const samples = demo ? demoResourceSamples(nodes.find((s) => s.serverId === target)) : histories[target] ?? []
  const points = resourceHistory(samples, historyMetric)
  const yTitle = historyMetric === 'mem_used_bytes' ? '메모리 (MiB)' : historyMetric === 'cpu_cores' ? 'CPU 사용량 (core)' : '사용률 (%)'
  const divisor = historyMetric === 'mem_used_bytes' ? 1048576 : 1
  const error = demo ? null : historyErrors[target]
  return <section className="silo-group-panel" aria-label="사일로 자원 시계열">
    <div className="data-subhead"><i className="fa-solid fa-chart-area" /> 사일로 자원 시계열</div>
    <div className="silo-history-toolbar">
      <div className="control-group"><label htmlFor="silo-history-target">사일로</label>
        <select id="silo-history-target" className="model-input" value={target} onChange={(e) => selectHistory(e.target.value)}>
          {nodes.map((s) => <option key={s.serverId} value={s.serverId}>{s.name}</option>)}</select></div>
      <div className="control-group"><label htmlFor="silo-history-metric">지표</label>
        <select id="silo-history-metric" className="model-input" value={historyMetric} onChange={(e) => selectHistory(target, e.target.value as ResourceHistoryMetric)}>
          <option value="cpu">CPU %</option><option value="cpu_cores">CPU core</option><option value="mem">메모리 %</option><option value="mem_used_bytes">메모리 MiB</option><option value="disk">디스크 %</option></select></div>
    </div>
    {error ? <p role="alert" className="text-red">시계열 조회 실패: {error}</p> : points.length === 0 ? <div className="deploy-empty">수집된 표본이 없습니다. 수집 주기가 지나면 표시됩니다.</div> : <>
      <SiloTrendChart input={{ labels: points.map((p) => p.timestamp.slice(11, 19)), series: [{ siloId: target, values: points.map((p) => p.value === null ? null : p.value / divisor) }] }} yTitle={yTitle} connectGaps={false} />
      <p className="desc">수집 시각: {points[0].timestamp} ~ {points[points.length - 1].timestamp}. 미측정 표본은 선으로 연결하지 않습니다.</p>
      {points.every((p) => p.value === null) && <p className="desc">이 구간에는 해당 지표의 측정값이 없습니다. 사일로 카드에서 측정 범위와 실제 사용량을 확인하세요.</p>}
    </>}
  </section>
}
