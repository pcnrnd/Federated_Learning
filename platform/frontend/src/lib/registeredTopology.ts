import type { TopologyPayload } from '@/api/client'
import type { Silo } from '@/types/simulation'

/** 실제 serverId를 그대로 사용한다. 표시용 숫자 별칭으로 노드를 합치지 않는다. */
export function registeredTopology(silos: readonly Silo[]): TopologyPayload {
  const live = silos.filter((s) => s.serverId)
  if (!live.length) return { nodes: [], edges: [] }
  const ids = new Set(live.map((s) => s.serverId!))
  const central = 'central:server'
  return { nodes: [{ id: central, label: '중앙 서버', role: 'central', group: null, over_budget: null },
    ...live.map((s) => ({ id: `silo:${s.serverId}`, label: `${s.name} (${s.serverId})`,
      role: live.some((c) => c.parentServerId === s.serverId) ? 'aggregator' as const : 'client' as const,
      group: null, over_budget: s.resourceGate === 'over_budget' ? true : null }))],
    edges: live.map((s) => ({ source: s.parentServerId && ids.has(s.parentServerId) ? `silo:${s.parentServerId}` : central,
      target: `silo:${s.serverId}`,
      kind: 'aggregation' as const, metadata: {} })) }
}
