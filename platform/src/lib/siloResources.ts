import type { ResourceLimit, ResourceSampleApi, ResourceUsageSummary, SiloGroupApi, SiloRegistrationApi } from '@/api/client'
import type { Silo, SiloThresholds, ResourceHistoryMetric } from '@/types/simulation'

// 숫자 ID는 기존 표시/선택 코드와의 호환 별칭이다. 실제 액션 키는 serverId다.
const numericAliases = new Map<string, number>()
let nextAlias = -1

export function registeredSiloNumber(id: string): number {
  const existing = numericAliases.get(id)
  if (existing !== undefined) return existing
  const match = /^silo-(0|[1-9]\d*)$/.exec(id)
  const canonical = match ? Number(match[1]) : NaN
  const alias = Number.isSafeInteger(canonical) ? canonical : nextAlias--
  numericAliases.set(id, alias)
  return alias
}

export function siloActionKey(silo: Silo): string | number {
  return silo.serverId ?? silo.id
}

export function siloDraftKey(key: string | number): string {
  return `${typeof key === 'string' ? 'server' : 'demo'}:${key}`
}

export function refreshSiloObservation(silo: Silo, now = Date.now(), connectionFailed = false): Silo {
  if (!silo.serverId) return silo
  const age = silo.lastSampleAt ? now - Date.parse(silo.lastSampleAt) : NaN
  const hasValues = silo.cpu !== null || silo.mem !== null || silo.cpuCores != null || silo.memUsedBytes != null
  const sampleState = !Number.isFinite(age) ? 'uncollected'
    : age < 0 || age > Math.max(silo.collectIntervalSec * 3, 60) * 1000 ? 'stale'
    : hasValues ? 'fresh'
    : silo.capabilities?.cpu_pct === false && silo.capabilities?.mem_pct === false ? 'unsupported' : 'unverified'
  return { ...silo, sampleState,
    resourceGate: connectionFailed || sampleState !== 'fresh'
      ? silo.resourceGate === 'unmonitored' ? 'unmonitored' : 'unknown' : silo.resourceGate }
}

export function mapRegisteredSilos(
  registrations: readonly SiloRegistrationApi[],
  usage: readonly ResourceUsageSummary[],
  limits: readonly ResourceLimit[],
  groups: readonly SiloGroupApi[],
  now = Date.now(),
): Silo[] {
  return registrations.map((r) => {
    const sample = usage.find((u) => u.silo_id === r.silo_id)
    const limit = limits.find((l) => l.silo_id === r.silo_id)
    const parent = groups.find((g) => g.aggregator_node_id && g.member_node_ids.includes(r.silo_id))
    const value = (metric: keyof SiloThresholds) => sample?.measurement_scope?.[metric]
      ? sample[`${metric}_pct`] : null
    return refreshSiloObservation({
      id: registeredSiloNumber(r.silo_id), serverId: r.silo_id,
      name: r.label, endpoint: r.base_url, collectIntervalSec: r.collect_interval_seconds,
      cpu: value('cpu'), mem: value('mem'), disk: value('disk'),
      thresholds: { cpu: limit?.cpu_pct_max ?? null, mem: limit?.mem_pct_max ?? null, disk: limit?.disk_pct_max ?? null },
      ...(parent?.aggregator_node_id ? { parentId: registeredSiloNumber(parent.aggregator_node_id) } : {}),
      parentServerId: parent?.aggregator_node_id ?? undefined,
      lastSampleAt: sample?.last_sample_at,
      measurementScope: sample?.measurement_scope ?? {}, unavailable: sample?.unavailable ?? {},
      cpuCores: sample?.measurement_scope?.cpu_cores ? sample.cpu_cores : null,
      memUsedBytes: sample?.measurement_scope?.mem_used_bytes ? sample.mem_used_bytes : null,
      capabilities: sample?.capabilities,
      resourceGate: sample?.availability ?? (limit ? 'unknown' : 'unmonitored'),
      gpuThreshold: limit?.gpu_pct_max ?? null,
    }, now)
  })
}

export function exceedsThreshold(value: number | null, threshold: number | null): boolean {
  return value !== null && threshold !== null && value > threshold
}

/** 미수집 구간을 이어서 정상 관측처럼 보이게 하지 않는다. */
export function resourceHistory(samples: readonly ResourceSampleApi[], metric: ResourceHistoryMetric) {
  const key = metric === 'cpu_cores' || metric === 'mem_used_bytes' ? metric : `${metric}_pct` as const
  return [...samples].sort((a, b) => a.timestamp.localeCompare(b.timestamp)).map((s) => ({
    timestamp: s.timestamp,
    value: s.measurement_scope?.[metric] ? s[key] ?? null : null,
  }))
}
