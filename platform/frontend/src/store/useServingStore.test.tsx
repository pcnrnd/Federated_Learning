import '@/test/currentSnapshotSsr'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ServingComparison, ServingRoute } from '@/types/simulation'
import { useSimulationStore } from './useSimulationStore'
import { useServingStore as store } from './useServingStore'
import { ServingRoutesPanel } from '@/components/models/ServingRoutesPanel'

const { get, mutation } = vi.hoisted(() => ({ get: vi.fn(), mutation: vi.fn() }))
vi.mock('@/api/client', () => ({ apiGet: get, apiMutation: mutation, apiPost: vi.fn(), isLiveConfigured: () => true }))

const route: ServingRoute = { route_id: 'actual-route', primary_deployment_id: 'real-primary', shadow_deployment_id: 'real-shadow',
  previous_deployment_id: null, shadow_id: 'shadow-id', status: 'active', generation: 2, mirror_pct: 100,
  comparison_gate: null, comparison_started_at: null, created_at: 'today', changed_at: 'today',
  cleanup_deployment_ids: [], cleanup_pending: false, error: null }
const comparison: ServingComparison = { route_id: route.route_id, generation: 2, window_start: 'observed-start',
  window_end: 'observed-end', window_seconds: 60, request_count: 2, pending: 0, interrupted: 0, pairs: 1,
  difference_count: 1, mean_abs_difference: 2, latest_pair_at: 'observed-pair', roles: {
    primary: { requests: 2, successes: 2, errors: 0, interrupted: 0, measured_requests: 2, mean_latency_ms: 12, throughput_rps: .1 },
    shadow: { requests: 2, successes: 1, errors: 1, interrupted: 0, measured_requests: 1, mean_latency_ms: 15, throughput_rps: .1 },
  }, paired_roles: {}, gate_ready: false, gate_reasons: ['실제 오류율 기준 미충족'], gate: null }
function snapshot() {
  get.mockImplementation(async (path: string) => path === '/api/serving-routes' ? [route]
    : path.endsWith('/comparison') ? comparison : [])
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done }); return { promise, resolve } }

beforeEach(() => { vi.clearAllMocks(); useSimulationStore.setState({ mockEnabled: false }); store.getState().clear(); snapshot() })
afterEach(() => { vi.restoreAllMocks() })

test('늦은 poll은 경로 선택/새 snapshot을 덮어쓰지 않고 실패는 관측과 오류를 보존한다', async () => {
  const late = deferred<ServingRoute[]>()
  get.mockImplementation((path: string) => path === '/api/serving-routes' ? late.promise : Promise.resolve([]))
  const old = store.getState().poll()
  store.getState().clear()
  snapshot()
  expect(await store.getState().poll()).toBe(true)
  late.resolve([{ ...route, route_id: 'obsolete' }]); await old
  expect(store.getState().selected).toBe('actual-route')
  get.mockRejectedValue(new Error('HTTP 503'))
  expect(await store.getState().poll()).toBe(false)
  expect(store.getState()).toMatchObject({ routes: [route], comparison, error: 'HTTP 503' })
})

test('요청은 실제 route에 전송하고 state/log에는 입력과 예측을 보관하지 않는다', async () => {
  await store.getState().poll()
  mutation.mockResolvedValue({ request_id: 'a'.repeat(32), deployment_id: 'real-primary', version: '1.0.0',
    input_count: 1, predictions: ['private-prediction'] })
  expect(await store.getState().predict([['private-feature']])).toBe(true)
  expect(mutation).toHaveBeenCalledWith('POST', '/api/serving-routes/actual-route/predict', {
    inputs: [['private-feature']], request_id: expect.stringMatching(/^[a-f0-9]{32}$/),
  })
  const serialized = JSON.stringify(store.getState())
  expect(serialized).not.toContain('private-feature')
  expect(serialized).not.toContain('private-prediction')
  expect(store.getState().lastResponse?.deployment_id).toBe('real-primary')
})

test('모드 off/on 이후 늦은 mutation은 이전 실제 결과/오류/pending을 되살리지 않는다', async () => {
  await store.getState().poll()
  const late = deferred<Record<string, unknown>>()
  mutation.mockReturnValue(late.promise)
  const request = store.getState().action('promote')
  useSimulationStore.setState({ mockEnabled: true })
  useSimulationStore.setState({ mockEnabled: false })
  late.resolve({ status: 'promoted' })
  expect(await request).toBe(false)
  expect(store.getState()).toMatchObject({ routes: [], pending: false, error: null, lastResponse: null })
})

test('승격 거부와 실제 비교 N/window/역할별 측정 오류는 화면에 그대로 남는다', async () => {
  await store.getState().poll()
  mutation.mockRejectedValue(new Error('HTTP 409 실제 gate 미충족'))
  expect(await store.getState().action('promote')).toBe(false)
  expect(store.getState().routes[0].primary_deployment_id).toBe('real-primary')
  const html = renderToStaticMarkup(<ServingRoutesPanel />)
  for (const value of ['observed-start', 'observed-end', '실제 gate 미충족', 'real-primary', 'real-shadow', '예측 차이는 정확도 지표가 아닙니다']) {
    expect(html).toContain(value)
  }
})
