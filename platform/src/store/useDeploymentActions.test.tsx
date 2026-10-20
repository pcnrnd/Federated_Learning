import '@/test/currentSnapshotSsr'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

beforeEach(() => { vi.resetModules(); vi.stubEnv('VITE_API_BASE', 'http://central') })
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals() })

async function world() {
  const { useSimulationStore } = await import('./useSimulationStore')
  useSimulationStore.setState({ mockEnabled: false, log: vi.fn() })
  const { useSiloStore } = await import('./useSiloStore')
  useSiloStore.setState({ silos: [{ id: 1, serverId: 'silo-01', name: '표시 이름', endpoint: '', collectIntervalSec: 5,
    cpu: null, mem: null, disk: null, thresholds: { cpu: null, mem: null, disk: null } }] })
  const { useModelStore: store } = await import('./useModelStore')
  const { modelKey } = await import('@/api/mappers')
  const id = modelKey('m', '1.0.0')
  store.getState().clearAll()
  store.setState({ models: [{ id, project: 'm', version: '1.0.0', status: 'experimental', accuracy: 0,
    algorithm: 'fedavg', rounds: 1, createdAt: 'today' }] })
  return { store, id, simulation: useSimulationStore }
}

test('timeout 재시도는 같은 request ID, 확인 뒤 새 명령은 새 ID이며 서버 pending을 완료로 바꾸지 않는다', async () => {
  const { store, id } = await world()
  const writes: Array<Record<string, unknown>> = []
  let fail = true
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      writes.push(JSON.parse(init.body as string))
      if (fail) throw new Error('timeout after reserve')
      return new Response('{}', { status: 201 })
    }
    const value = url.endsWith('/api/models') ? [{ name: 'm', version: '1.0.0', metadata: {}, created_at: 'today' }]
      : url.endsWith('/api/deployments') ? [{ deployment_id: 'pending-id', model_name: 'm', version: '1.0.0',
        image_tag: 'image', strategy: 'realtime', target_node_ids: ['silo-01'], status: 'pending', created_at: 'now',
        previous_deployment_id: null, error: null }] : []
    return new Response(JSON.stringify(value))
  }))
  const input = { modelId: id, strategy: 'realtime' as const, targetSiloIds: [1], env: { APP: 'preserved' } }
  store.getState().createDeployment(input)
  await vi.waitFor(() => { expect(writes).toHaveLength(1); expect(store.getState().liveModelPending).toBe(false) })
  fail = false
  store.getState().createDeployment(input)
  await vi.waitFor(() => { expect(writes).toHaveLength(2); expect(store.getState().liveModelPending).toBe(false) })
  expect(writes[1]).toEqual(writes[0])
  expect(store.getState().deployments[0].state).toBe('pending')
  store.getState().createDeployment(input)
  await vi.waitFor(() => { expect(writes).toHaveLength(3); expect(store.getState().liveModelPending).toBe(false) })
  expect(writes[2].request_id).not.toBe(writes[0].request_id)
  expect(writes[0]).toMatchObject({ target_node_ids: ['silo-01'], env: { APP: 'preserved' } })
})

test('모드 변경 뒤 늦은 배포 응답은 이전 catalog/error/pending을 되살리지 않는다', async () => {
  const { store, id, simulation } = await world()
  let reject!: (error: Error) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise((_resolve, failed) => { reject = failed })))
  store.getState().createDeployment({ modelId: id, strategy: 'realtime', targetSiloIds: [1] })
  expect(store.getState().liveModelPending).toBe(true)
  simulation.setState({ mockEnabled: true })
  store.getState().clearAll()
  reject(new Error('old late failure'))
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
  expect(store.getState()).toMatchObject({ models: [], deployments: [], liveModelPending: false, liveModelError: null,
    liveDeploymentRequests: {} })
})

test('일정/대상별 실측 상태와 서버 오류를 렌더링하며 env 값은 목록에 표시하지 않는다', async () => {
  const { store, id } = await world()
  store.setState({ liveModelError: '서버 실제 오류', deployments: [{ id: 'schedule', modelId: id, modelLabel: 'm 1.0.0',
    strategy: 'batch', targetSiloIds: [1], targetNodeIds: ['silo-01'], intervalSec: 30, state: 'failed', ts: 'now',
    isSchedule: true, scheduleActive: false, occurrence: 2, nextDueAt: 'actual-due', env: { APP: 'private-value' },
    imageId: 'sha256:actual', cleanupPending: true, error: '정리 미확인',
    targets: { 'silo-01': { status: 'failed', endpoint: 'http://silo-01:31001', error_code: 'ValueError' } } }] })
  const { DeploymentTimeline } = await import('@/components/models/DeploymentTimeline')
  const { StrategyForm } = await import('@/components/models/StrategyForm')
  const html = renderToStaticMarkup(<DeploymentTimeline />)
  expect(html).toContain('silo-01: 실패')
  expect(html).toContain('http://silo-01:31001')
  expect(html).toContain('actual-due')
  expect(html).toContain('정리 재시도')
  expect(html).toContain('서버 실제 오류')
  expect(html).not.toContain('private-value')
  const form = renderToStaticMarkup(<StrategyForm modelId={id} packaged />)
  expect(form).toContain('환경변수')
  expect(form).toContain('서버 설정 불러오기')
  expect(form).toContain('대상 사일로 선택')
})

test.each(['/api/deployments', '/api/serving-routes/actual/predict', '/api/shadow-deployments'])('validation input/env 값은 사용자 로그로 복사하지 않는다: %s', async (path) => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'env'],
    msg: 'Value error, 환경변수 이름을 확인하세요', input: { SECRET: 'private-value' } }] }), { status: 422 })))
  const { apiPost } = await import('@/api/client')
  await expect(apiPost(path, {})).rejects.toThrow('body.env')
  await expect(apiPost(path, {})).rejects.not.toThrow('private-value')
})

test('G5-A-F1 archived 모델 행 복원은 선택 JSON identity를 보내고 과거 실행 previous endpoint를 호출하지 않는다', async () => {
  const { store, id } = await world()
  store.setState((state) => ({ models: state.models.map((model) => ({ ...model, status: 'archived' })) }))
  const writes: Array<{ url: string; body: unknown }> = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      writes.push({ url, body: JSON.parse(init.body as string) })
      return new Response('{}')
    }
    return new Response(JSON.stringify(url.endsWith('/api/models') ? [{ name: 'm', version: '1.0.0',
      status: 'active', metadata: {}, created_at: 'today' }] : []))
  }))
  store.getState().rollbackModel(id)
  await vi.waitFor(() => { expect(writes).toHaveLength(1); expect(store.getState().liveModelPending).toBe(false) })
  expect(writes[0]).toEqual({ url: 'http://central/api/deployments/restore-model', body: {
    name: 'm', version: '1.0.0', request_id: expect.stringMatching(/^[a-f0-9]{32}$/),
  } })
})
