import { afterEach, beforeEach, expect, test, vi } from 'vitest'

beforeEach(() => { vi.resetModules(); vi.stubEnv('VITE_API_BASE', 'http://central') })
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs() })

test('live cleaning 401 preserves the previous result and exposes a failed save', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":"unauthorized"}', { status: 401 })))
  const { useDataStore } = await import('@/store/useDataStore')
  useDataStore.getState().patchLiveDraft({ job_id: 'saved', recipe_name: 'r', group_id: 'g' })
  const before = useDataStore.getState().dataBySilo
  expect(await useDataStore.getState().createLiveJob()).toBe(false)
  expect(useDataStore.getState().liveError).toContain('HTTP 401')
  expect(useDataStore.getState().livePending).toBe(false)
  expect(useDataStore.getState().dataBySilo).toBe(before)
})

test('live schedule and reschedule send stored times/dependencies and wait for server results', async () => {
  const writes: Array<{ url: string; body: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') writes.push({ url, body: JSON.parse(init.body as string) })
    return new Response(JSON.stringify(init?.method === 'POST' ? {} : []))
  }))
  const { useDataStore } = await import('@/store/useDataStore')
  const { useSimulationStore } = await import('@/store/useSimulationStore')
  useSimulationStore.setState({ mockEnabled: false })
  useDataStore.getState().patchLiveDraft({ job_id: 'j', recipe_name: 'r', group_id: 'g',
    depends_on: 'pre, other', scheduled_at: '2026-10-19T01:00:00Z', interval_seconds: '60' })
  expect(await useDataStore.getState().createLiveJob()).toBe(true)
  expect(writes[0].body).toMatchObject({ scheduled_at: '2026-10-19T01:00:00.000Z',
    depends_on: ['pre', 'other'], interval_seconds: 60, partitions: 4, parallelism: 2 })
  expect(await useDataStore.getState().rescheduleLiveJob('j', '2026-10-19T02:00:00Z')).toBe(true)
  expect(writes[1]).toEqual({ url: 'http://central/api/cleaning-jobs/j/reschedule', body: { scheduled_at: '2026-10-19T02:00:00.000Z' } })
})

test('the same persisted final failure event creates one internal notification across polls', async () => {
  const { useDataStore } = await import('@/store/useDataStore')
  const { useSimulationStore } = await import('@/store/useSimulationStore')
  const log = vi.fn()
  useSimulationStore.setState({ mockEnabled: false, log })
  const jobs = [{ jobId: 'j', recipe: 'r@1', status: 'failed' as const, datasetLabel: 'local',
    totalRowsIn: 0, totalRowsOut: 0, counters: {}, updatedAt: 'now',
    events: [{ event_id: 'j:0:final_failure', kind: 'failed', message: '시도 소진', at: 'now' }] }]
  useDataStore.getState().applyLiveCleaning({}, jobs)
  useDataStore.getState().applyLiveCleaning({}, jobs)
  expect(log).toHaveBeenCalledTimes(1)
  useDataStore.getState().applyLiveCleaning({}, [{ ...jobs[0], events: [{ ...jobs[0].events[0], event_id: 'j:1:final_failure' }] }])
  expect(log).toHaveBeenCalledTimes(2)
})
