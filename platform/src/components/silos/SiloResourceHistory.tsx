import { useEffect } from 'react'
import { useSiloStore } from '@/store/useSiloStore'
import { resourceHistory } from '@/lib/siloResources'
import { SiloTrendChart } from '@/components/visualization/SiloTrendChart'
import type { ResourceHistoryMetric } from '@/types/simulation'

export function SiloResourceHistory() {
  const { silos, selectedHistorySilo, historyMetric, selectHistory, loadHistory, histories, historyErrors } = useSiloStore()
  const target = silos.find((s) => s.serverId === selectedHistorySilo)?.serverId ?? silos[0]?.serverId
  useEffect(() => {
    if (!target) return
    void loadHistory(target)
    const timer = window.setInterval(() => void loadHistory(target), 5000)
    return () => window.clearInterval(timer)
  }, [target, loadHistory])
  if (!target) return null
  const points = resourceHistory(histories[target] ?? [], historyMetric)
  const yTitle = historyMetric === 'mem_used_bytes' ? '메모리 (MiB)' : historyMetric === 'cpu_cores' ? 'CPU 사용량 (core)' : '사용률 (%)'
  const divisor = historyMetric === 'mem_used_bytes' ? 1048576 : 1
  const error = historyErrors[target]
  return <section className="silo-group-panel" aria-label="사일로 자원 시계열">
    <h3>사일로 자원 시계열</h3>
    <div className="model-toolbar">
      <label>사일로 <select className="model-input" value={target} onChange={(e) => selectHistory(e.target.value)}>{silos.filter((s) => s.serverId).map((s) => <option key={s.serverId} value={s.serverId}>{s.name} ({s.serverId})</option>)}</select></label>
      <label>지표 <select className="model-input" value={historyMetric} onChange={(e) => selectHistory(target, e.target.value as ResourceHistoryMetric)}><option value="cpu">CPU %</option><option value="cpu_cores">CPU core</option><option value="mem">메모리 %</option><option value="mem_used_bytes">메모리 MiB</option><option value="disk">디스크 %</option></select></label>
    </div>
    {error ? <p role="alert" className="text-red">시계열 조회 실패: {error}</p> : points.length === 0 ? <p>수집된 표본이 없습니다.</p> : <>
      <SiloTrendChart input={{ labels: points.map((p) => p.timestamp.slice(11, 19)), series: [{ siloId: target, values: points.map((p) => p.value === null ? null : p.value / divisor) }] }} yTitle={yTitle} connectGaps={false} />
      <p className="silo-observation">수집 시각: {points[0].timestamp} ~ {points[points.length - 1].timestamp}. 미측정 표본은 선으로 연결하지 않습니다.</p>
      {points.every((p) => p.value === null) && <p>이 구간에는 해당 지표의 측정값이 없습니다. 사일로 카드에서 측정 범위와 실제 사용량을 확인하세요.</p>}
    </>}
  </section>
}
