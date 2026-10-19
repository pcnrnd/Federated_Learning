import { afterEach, beforeEach, expect, test, vi } from 'vitest'

beforeEach(() => {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE', 'http://central')
})
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs() })

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
  expect(useSiloStore.getState().mutationError).toContain('HTTP 401')
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
  expect(await useSiloStore.getState().updateThreshold(1, { cpu: 70 })).toBe(true)
  expect(calls[0]).toContain('POST http://central/api/resources/limits')
  expect(useSiloStore.getState().silos[0].thresholds.cpu).toBe(70)
})
