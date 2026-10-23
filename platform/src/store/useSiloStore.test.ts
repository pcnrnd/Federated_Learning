import { afterEach, beforeEach, expect, test, vi } from 'vitest'

beforeEach(() => {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE', 'http://central')
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.unstubAllEnvs() })

test('401 live registration preserves server state and exposes the failure', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":"API key required"}', { status: 401 })))
  const { useSiloStore } = await import('@/store/useSiloStore')
  const { useSimulationStore } = await import('@/store/useSimulationStore')
  useSimulationStore.setState({ mockEnabled: false })
  useSiloStore.setState({ silos: [], pending: false, mutationError: null })
  const result = await useSiloStore.getState().addSilo({ siloId: 'silo-7', name: '등록 실패', endpoint: 'tcp://silo-7:2375', collectIntervalSec: 15 })
  expect(result).toBe(false)
  expect(useSiloStore.getState().silos).toEqual([])
  expect(useSiloStore.getState().pending).toBe(false)
  expect(useSiloStore.getState().mutationError).toBe('권한이 없어 요청을 처리할 수 없습니다')
})

test('live threshold save waits for the server and refreshes persisted limits', async () => {
  const registration = { silo_id: 'silo-1', label: '기관', base_url: 'tcp://silo-1:2375', collect_interval_seconds: 15 }
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${url}`)
    const body = url.endsWith('/api/silos') ? [registration]
      : url.endsWith('/api/resources/usage') || url.endsWith('/api/silo-groups') ? []
      : init?.method === 'POST' ? JSON.parse(init.body as string)
      : [{ silo_id: 'silo-1', cpu_pct_max: 70, mem_pct_max: null, disk_pct_max: null, gpu_pct_max: null }]
    return new Response(JSON.stringify(body), { status: 200 })
  }))
  const { useSiloStore } = await import('@/store/useSiloStore')
  const { useSimulationStore } = await import('@/store/useSimulationStore')
  useSimulationStore.setState({ mockEnabled: false })
  useSiloStore.setState({ silos: [{ id: 1, serverId: 'silo-1', name: '기관', endpoint: registration.base_url, collectIntervalSec: 15, cpu: null, mem: null, disk: null, thresholds: { cpu: null, mem: null, disk: null } }], pending: false })
  expect(await useSiloStore.getState().updateThreshold('silo-1', { cpu: 70 })).toBe(true)
  expect(calls[0]).toContain('POST http://central/api/resources/limits')
  expect(useSiloStore.getState().silos[0].thresholds.cpu).toBe(70)
})

test('G1-F1 live mutations and drafts address exact server IDs even with colliding legacy aliases', async () => {
  const nodes = ['silo-1', 'silo-01'].map((silo_id) => ({ silo_id, label: silo_id, base_url: `tcp://${silo_id}:2375`, collect_interval_seconds: 15 }))
  let registrations = [...nodes]
  const writes: Array<{ method: string; url: string; body: Record<string, unknown> | null }> = []
  const limits: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (method !== 'GET') {
      const body = init?.body ? JSON.parse(init.body as string) : null
      writes.push({ method, url, body })
      if (method === 'POST') limits.push(body)
      if (method === 'DELETE') registrations = registrations.filter((r) => !url.endsWith(`/${r.silo_id}`))
      return new Response(JSON.stringify(body ?? { ok: true }))
    }
    const result = url.endsWith('/api/silos') ? registrations : url.endsWith('/api/resources/limits') ? limits : []
    return new Response(JSON.stringify(result))
  }))
  const { useSiloStore } = await import('@/store/useSiloStore')
  const { useSimulationStore } = await import('@/store/useSimulationStore')
  const { siloDraftKey } = await import('@/lib/siloResources')
  useSimulationStore.setState({ mockEnabled: false })
  useSiloStore.setState({ silos: nodes.map((r) => ({ id: 1, serverId: r.silo_id, name: r.label, endpoint: r.base_url, collectIntervalSec: 15, cpu: null, mem: null, disk: null, thresholds: { cpu: null, mem: null, disk: null } })), pending: false, thresholdDrafts: {} })
  useSiloStore.getState().editThreshold('silo-1', { cpu: 60 })
  useSiloStore.getState().editThreshold('silo-01', { cpu: 70 })
  expect(useSiloStore.getState().thresholdDrafts[siloDraftKey('silo-1')].cpu).toBe(60)
  expect(useSiloStore.getState().thresholdDrafts[siloDraftKey('silo-01')].cpu).toBe(70)
  expect(await useSiloStore.getState().updateThreshold('silo-01', { cpu: 70 })).toBe(true)
  expect(writes[0].body?.silo_id).toBe('silo-01')
  expect(await useSiloStore.getState().updateThreshold('silo-1', { cpu: 60 })).toBe(true)
  expect(writes[1].body?.silo_id).toBe('silo-1')
  expect(await useSiloStore.getState().removeSilo(1)).toBe(false)
  expect(await useSiloStore.getState().removeSilo('silo-01')).toBe(true)
  expect(writes[2].url).toBe('http://central/api/silos/silo-01')
  expect(await useSiloStore.getState().removeSilo('silo-1')).toBe(true)
  expect(writes[3].url).toBe('http://central/api/silos/silo-1')
})

test('G1-F4 success then polling failure and elapsed time invalidate collection status until recovery', async () => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-10-19T00:00:00Z'))
  let fail = false
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (fail) return new Response('{"detail":"unauthorized"}', { status: 401 })
    const body = url.endsWith('/api/silos') ? [{ silo_id: 'silo-1', label: '기관', base_url: 'tcp://silo-1:2375', collect_interval_seconds: 15 }]
      : url.endsWith('/api/resources/usage') ? [{ silo_id: 'silo-1', last_sample_at: new Date().toISOString(), cpu_pct: 10, mem_pct: null, disk_pct: null, gpu_pct: null, measurement_scope: { cpu: 'own cgroup' }, over_budget: false, availability: 'available' }]
      : url.endsWith('/api/resources/limits') ? [{ silo_id: 'silo-1', cpu_pct_max: 80, mem_pct_max: null, disk_pct_max: null, gpu_pct_max: null }] : []
    return new Response(JSON.stringify(body))
  }))
  const { useSiloStore } = await import('@/store/useSiloStore')
  const { useSimulationStore } = await import('@/store/useSimulationStore')
  useSimulationStore.setState({ mockEnabled: false })
  await useSiloStore.getState().refreshLive()
  expect(useSiloStore.getState().silos[0].sampleState).toBe('fresh')
  expect(useSiloStore.getState().silos[0].resourceGate).toBe('available')
  fail = true
  await expect(useSiloStore.getState().refreshLive()).rejects.toThrow('권한이 없어')
  expect(useSiloStore.getState().pollError).toContain('권한이 없어')
  expect(useSiloStore.getState().silos[0].resourceGate).toBe('unknown')
  vi.setSystemTime(new Date('2026-10-19T00:02:00Z'))
  useSiloStore.getState().refreshObservationState()
  expect(useSiloStore.getState().silos[0]).toMatchObject({ sampleState: 'stale', cpu: 10, resourceGate: 'unknown', lastSampleAt: '2026-10-19T00:00:00.000Z' })
  fail = false
  await useSiloStore.getState().refreshLive()
  expect(useSiloStore.getState().pollError).toBeNull()
  expect(useSiloStore.getState().silos[0]).toMatchObject({ sampleState: 'fresh', resourceGate: 'available' })
})
