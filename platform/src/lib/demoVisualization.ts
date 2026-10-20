import { baselineKey } from '@/api/mappers'
import type { VizQuery, VizSnapshot } from '@/hooks/useVisualizationData'

const silos = Array.from({ length: 6 }, (_, i) => `silo-${i + 1}`)
const rounds = ['demo-round-1', 'demo-round-2', 'demo-round-3', 'demo-round-4']
const counts = [120, 150, 180, 210, 240, 270]

/** 기존 5종 차트와 같은 DTO. 시간·난수·서버 응답에 의존하지 않는 데모 입력이다. */
export function demoVisualization(query: VizQuery): VizSnapshot {
  const baseline = { model_name: query.modelName ?? '데모 모델', version: query.modelVersion ?? 'v1.0', feature: '측정 항목 A', bin_count: 5 }
  const key = baselineKey(baseline)
  return { query, failed: [], loading: [], data: {
    trend: { series: Object.fromEntries(silos.map((id, i) => [id, rounds.map((_, j) => ({
      timestamp: `2026-10-20T00:0${j}:00Z`,
      value: query.trendMetric === 'accuracy' ? (76 + i + j * 3) / 100
        : query.trendMetric === 'latency_ms' ? 48 + i * 4 - j * 2 : 24 + i * 3 + j * 4,
    }))])) },
    participation: { row_labels: silos, col_labels: rounds,
      col_meta: rounds.map((id, i) => ({ round_id: id, status: 'completed' as const, created_at: `2026-10-20T00:0${i}:00Z`, group_id: 'demo-group' })),
      matrix: counts.map((count) => rounds.map(() => count)),
      cell_status: silos.map(() => rounds.map(() => 'contributed' as const)) },
    roundBar: { roundId: rounds[3], payload: { items: silos.map((silo_id, i) => ({ silo_id, value: counts[i] })) } },
    resourceBar: { items: silos.map((silo_id, i) => ({ silo_id,
      value: (query.resourceMetric === 'cpu_pct' ? 26 : query.resourceMetric === 'mem_pct' ? 37
        : query.resourceMetric === 'gpu_pct' ? 18 : 44) + i * 5 })) },
    baselines: [baseline], histogram: { key, payload: { bin_edges: [0, 20, 40, 60, 80, 100], bin_counts: [18, 42, 67, 49, 24] } },
    topology: { nodes: [{ id: 'central', label: '중앙 서버', role: 'central', group: null, over_budget: false },
      ...silos.map((id) => ({ id, label: id, role: 'client' as const, group: null, over_budget: false }))],
      edges: silos.map((id) => ({ source: 'central', target: id, kind: 'aggregation' as const, metadata: {} })) },
  } }
}
