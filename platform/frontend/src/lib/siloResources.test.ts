import { describe, expect, test } from 'vitest'
import { exceedsThreshold, mapRegisteredSilos, registeredSiloNumber, resourceHistory, siloDisplayName, siloActionKey, siloDraftKey } from '@/lib/siloResources'
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
  test('G1-F1 keeps valid leading-zero IDs, large IDs and exact action keys distinct', () => {
    const ids = ['silo-1', 'silo-01', 'silo-9007199254740992', 'silo-9007199254740993', 'hospital-A']
    const registrations = ids.map((silo_id) => ({ ...registered[0], silo_id }))
    const mapped = mapRegisteredSilos(registrations, [], [], [])
    expect(new Set(mapped.map((s) => s.id)).size).toBe(ids.length)
    expect(mapped.map(siloActionKey)).toEqual(ids)
    expect(new Set(mapped.map((s) => siloDraftKey(siloActionKey(s)))).size).toBe(ids.length)
    const reversed = mapRegisteredSilos([...registrations].reverse(), [], [], [])
    for (const silo of mapped) expect(reversed.find((s) => s.serverId === silo.serverId)?.id).toBe(silo.id)
    expect(siloDraftKey('1')).not.toBe(siloDraftKey(1))
  })
  test('retains registered nodes before collection, exact server identity and stored settings', () => {
    const silos = mapRegisteredSilos(registered, [observation], [], [{ group_id: 'edge', description: '', aggregator_node_id: 'silo-1', member_node_ids: ['hospital-A'] }], Date.parse(observation.last_sample_at))
    expect(silos[0]).toMatchObject({ name: '사일로1', serverId: 'silo-1', endpoint: 'tcp://silo-1:2375', cpu: 0.12, mem: null, memUsedBytes: 1048576, sampleState: 'fresh' })
    expect(silos[1]).toMatchObject({ serverId: 'hospital-A', cpu: null, sampleState: 'uncollected', parentId: 1 })
    expect(silos[1].parentServerId).toBe('silo-1')
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

test('silo-N 사일로는 서버 label과 관계없이 사일로N으로 표시하고 그 밖의 사일로는 label을 쓴다', () => {
  expect(siloDisplayName('silo-3', '데모 사일로 3')).toBe('사일로3')
  expect(siloDisplayName('silo-01', '실서버 기관')).toBe('사일로1')
  expect(siloDisplayName('hospital-A', '두 번째 기관')).toBe('두 번째 기관')
})
