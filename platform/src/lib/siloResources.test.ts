import { describe, expect, test } from 'vitest'
import { exceedsThreshold, mapRegisteredSilos, registeredSiloNumber, resourceHistory } from '@/lib/siloResources'
import type { ResourceUsageSummary, SiloRegistrationApi } from '@/api/client'

const registered: SiloRegistrationApi[] = [
  { silo_id: 'silo-1', label: '첫 기관', base_url: 'tcp://silo-1:2375', collect_interval_seconds: 15 },
  { silo_id: 'hospital-A', label: '두 번째 기관', base_url: 'tcp://hospital-A:2375', collect_interval_seconds: 30 },
]
const observation: ResourceUsageSummary = {
  silo_id: 'silo-1', cpu_pct: 0.12, mem_pct: null, disk_pct: null, gpu_pct: null,
  last_sample_at: '2026-10-19T00:00:00Z', over_budget: false,
  mem_used_bytes: 1048576, measurement_scope: { cpu: 'own cgroup', mem_used_bytes: 'own cgroup' },
  unavailable: { mem: 'unlimited' }, capabilities: { mem_pct: false },
}

describe('live silo resource mapping', () => {
  test('retains registered nodes before collection, exact server identity and stored settings', () => {
    const silos = mapRegisteredSilos(registered, [observation], [], [{ group_id: 'edge', description: '', aggregator_node_id: 'silo-1', member_node_ids: ['hospital-A'] }], Date.parse(observation.last_sample_at))
    expect(silos[0]).toMatchObject({ name: '첫 기관', serverId: 'silo-1', endpoint: 'tcp://silo-1:2375', cpu: 0.12, mem: null, memUsedBytes: 1048576, sampleState: 'fresh' })
    expect(silos[1]).toMatchObject({ serverId: 'hospital-A', cpu: null, sampleState: 'uncollected', parentId: 1 })
    expect(silos[0].thresholds).toEqual({ cpu: null, mem: null, disk: null })
    expect(registeredSiloNumber('hospital-A')).toBe(silos[1].id)
  })

  test('marks stale samples and conceals legacy host-wide percentages with unknown scope', () => {
    const [old] = mapRegisteredSilos(registered, [{ ...observation, measurement_scope: {}, mem_used_bytes: null }], [], [], Date.parse(observation.last_sample_at) + 120_000)
    expect(old.cpu).toBeNull()
    expect(old.sampleState).toBe('stale')
  })

  test('keeps actual absolute memory when no percent limit exists', () => {
    const [silo] = mapRegisteredSilos(registered, [{ ...observation, cpu_pct: null }], [], [], Date.parse(observation.last_sample_at))
    expect(silo.sampleState).toBe('fresh')
    expect(silo.memUsedBytes).toBe(1048576)
    expect(exceedsThreshold(null, 80)).toBe(false)
    expect(exceedsThreshold(81, null)).toBe(false)
    expect(exceedsThreshold(81, 80)).toBe(true)
  })

  test('sorts history, retains missing gaps and uses real memory scalars', () => {
    const samples = [
      { ...observation, timestamp: '2026-10-19T00:00:02Z' },
      { ...observation, timestamp: '2026-10-19T00:00:01Z', cpu_pct: null },
    ]
    expect(resourceHistory(samples, 'cpu').map((p) => p.value)).toEqual([null, 0.12])
    expect(resourceHistory(samples, 'mem_used_bytes').map((p) => p.value)).toEqual([1048576, 1048576])
  })
})
