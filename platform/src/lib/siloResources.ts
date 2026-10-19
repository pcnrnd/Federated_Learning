import type { ResourceLimit, ResourceSampleApi, ResourceUsageSummary, SiloGroupApi, SiloRegistrationApi } from '@/api/client'
import type { Silo, SiloThresholds, ResourceHistoryMetric } from '@/types/simulation'

/** 표시용 숫자 ID. 서버 요청은 항상 원래 serverId를 사용한다. */
export function registeredSiloNumber(id: string): number {
  const match = /^silo-(\d+)$/.exec(id)
  if (match) return Number(match[1])
  let hash = 2166136261
  for (const ch of id) hash = Math.imul(hash ^ ch.charCodeAt(0), 16777619)
  return -(Math.abs(hash) + 1)
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
    const age = sample ? now - Date.parse(sample.last_sample_at) : NaN
    const state = !Number.isFinite(age) ? 'uncollected'
      : age > Math.max(r.collect_interval_seconds * 3, 60) * 1000 ? 'stale'
      : value('cpu') === null && value('mem') === null
        && sample?.cpu_cores == null && sample?.mem_used_bytes == null ? 'unsupported' : 'fresh'
    return {
      id: registeredSiloNumber(r.silo_id), serverId: r.silo_id,
      name: r.label, endpoint: r.base_url, collectIntervalSec: r.collect_interval_seconds,
      cpu: value('cpu'), mem: value('mem'), disk: value('disk'),
      thresholds: { cpu: limit?.cpu_pct_max ?? null, mem: limit?.mem_pct_max ?? null, disk: limit?.disk_pct_max ?? null },
      ...(parent?.aggregator_node_id ? { parentId: registeredSiloNumber(parent.aggregator_node_id) } : {}),
      lastSampleAt: sample?.last_sample_at, sampleState: state,
      measurementScope: sample?.measurement_scope ?? {}, unavailable: sample?.unavailable ?? {},
      cpuCores: sample?.cpu_cores, memUsedBytes: sample?.mem_used_bytes,
      capabilities: sample?.capabilities,
      resourceGate: sample?.availability ?? (limit ? 'unknown' : 'unmonitored'),
      gpuThreshold: limit?.gpu_pct_max ?? null,
    }
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
