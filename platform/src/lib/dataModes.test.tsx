import '@/test/currentSnapshotSsr'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

beforeEach(() => { vi.resetModules(); vi.stubEnv('VITE_API_BASE', 'http://central') })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.unstubAllEnvs() })

async function stores() {
  const { useSimulationStore: mode } = await import('@/store/useSimulationStore')
  const { useDataStore: data } = await import('@/store/useDataStore')
  const { useSiloStore: silos } = await import('@/store/useSiloStore')
  const { useModelStore: models } = await import('@/store/useModelStore')
  return { mode, data, silos, models }
}

function timerWindow() {
  vi.stubGlobal('window', { setTimeout: (...args: Parameters<typeof setTimeout>) => setTimeout(...args),
    clearTimeout, localStorage: { getItem: () => null, setItem: vi.fn() } })
}

test('저장값 없는 LIVE 첫 렌더에는 네 도메인의 데모 seed가 없다', async () => {
  const { mode, data, silos, models } = await stores()
  expect(mode.getState().mockEnabled).toBe(false)
  expect(mode.getState().nodes).toEqual([])
  expect(mode.getState().chartPoints).toEqual([])
  expect(data.getState().jobs).toEqual([])
  expect(data.getState().dataBySilo).toEqual({})
  expect(silos.getState().silos).toEqual([])
  expect(models.getState().models).toEqual([])
  expect(models.getState().packages).toEqual({})
})

test('기존 설정 키의 저장값은 첫 렌더와 다음 새로고침에 일관되게 반영된다', async () => {
  const values = new Map([['fed-mock-enabled', 'true']])
  vi.stubGlobal('window', { localStorage: { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value) } })
  const first = await stores()
  expect(first.mode.getState().mockEnabled).toBe(true)
  expect(first.silos.getState().silos).toHaveLength(6)
  first.mode.getState().setMockEnabled(false)
  expect(values.get('fed-mock-enabled')).toBe('false')
  vi.resetModules()
  const reloaded = await stores()
  expect(reloaded.mode.getState().mockEnabled).toBe(false)
  expect(reloaded.silos.getState().silos).toEqual([])
  expect(reloaded.models.getState().models).toEqual([])
})

test('DEMO의 8개 메뉴는 같은 모드의 입력을 표시하고 서버를 호출하지 않는다', async () => {
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  const { mode } = await stores()
  mode.getState().setMockEnabled(true)
  const views = [
    [(await import('@/views/DashboardView')).DashboardView, '시뮬레이션 구성'],
    [(await import('@/views/NodesView')).NodesView, '로컬 데이터'],
    [(await import('@/views/SilosView')).SilosView, '등록 사일로'],
    [(await import('@/views/DataView')).DataView, '원본 레코드'],
    [(await import('@/views/ModelsView')).ModelsView, '프로젝트3'],
    [(await import('@/views/AnalyticsView')).AnalyticsView, '데이터 드리프트'],
    [(await import('@/views/VisualizationView')).VisualizationView, '사일로 × 라운드 참여 매트릭스'],
    [(await import('@/views/LogsView')).LogsView, '데모 데이터'],
  ] as const
  for (const [View, label] of views) {
    const html = renderToStaticMarkup(<View />)
    expect(html).toContain(label)
    expect(html).not.toContain('목 데이터')
  }
  expect(fetch).not.toHaveBeenCalled()
})

test('OFF+API 미설정은 데모 폼·타이머 실행으로 fallback하지 않는다', async () => {
  vi.stubEnv('VITE_API_BASE', '')
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  const { data, models } = await stores()
  const { JobScheduler } = await import('@/components/data/JobScheduler')
  const { NewModelForm } = await import('@/components/models/NewModelForm')
  expect(renderToStaticMarkup(<JobScheduler />)).toContain('API 주소 설정이 필요')
  expect(renderToStaticMarkup(<NewModelForm defaultProject="fixture" onClose={() => {}} />)).toContain('실데이터 API 주소 설정')
  data.getState().addJob({ name: '가짜 실행 금지', schedule: '*', dependsOn: [] })
  models.getState().addModel({ project: 'fake', version: '1.0.0', algorithm: 'fedavg', accuracy: 99, rounds: 1 })
  expect(data.getState().jobs).toEqual([])
  expect(models.getState().models).toEqual([])
  expect(fetch).not.toHaveBeenCalled()
})

test('DEMO 쓰기 격리는 폼 조건뿐 아니라 store와 최종 API 호출까지 적용된다', async () => {
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  const { mode, data, silos, models } = await stores()
  mode.getState().setMockEnabled(true)
  const { apiMutation } = await import('@/api/client')
  for (const method of ['POST', 'PUT', 'DELETE'] as const) await expect(apiMutation(method, '/api/models')).rejects.toThrow('서버를 변경하지 않습니다')
  expect(await data.getState().createLiveJob()).toBe(false)
  expect(await data.getState().rescheduleLiveJob('actual', '2026-10-20T00:00:00Z')).toBe(false)
  expect(await silos.getState().saveGroup({ group_id: 'actual', description: '', member_node_ids: [], aggregator_node_id: null }, false)).toBe(false)
  expect(await silos.getState().deleteGroup('actual')).toBe(false)
  expect(await models.getState().createLiveModel()).toBe(false)
  expect(fetch).not.toHaveBeenCalled()
})

test('이전 DEMO 타이머는 OFF 또는 다시 ON한 같은 작업 ID에도 쓸 수 없다', async () => {
  vi.useFakeTimers()
  timerWindow()
  const { mode, data, models } = await stores()
  const { JOB_STEP_MS, DEPLOY_TIMINGS } = await import('@/constants/simulation')
  mode.getState().setMockEnabled(true)
  const old = models.getState().models[0]
  data.getState().runJob('job-cleanse')
  models.getState().buildPackage(old.id, 'demo-runtime')
  models.getState().createDeployment({ modelId: old.id, strategy: 'realtime', targetSiloIds: [] })
  vi.advanceTimersByTime(1)
  mode.getState().setMockEnabled(false)
  mode.getState().setMockEnabled(true)
  data.getState().runJob('job-cleanse')
  vi.advanceTimersByTime(JOB_STEP_MS - 1)
  expect(data.getState().jobs.find((j) => j.id === 'job-cleanse')?.state).toBe('running')
  expect(models.getState().deployments).toEqual([])
  vi.advanceTimersByTime(1 + DEPLOY_TIMINGS.packageBuildMs + DEPLOY_TIMINGS.deployStepMs * 2)
  expect(models.getState().packages[old.id]).toBeUndefined()
  expect(models.getState().deployments).toEqual([])
  mode.getState().setMockEnabled(false)
  vi.runAllTimers()
  expect(data.getState().dataBySilo).toEqual({})
  expect(models.getState().packages).toEqual({})
})

const serverModel = { name: 'demo-like-name-returned-by-server', version: '1.0.0', framework: 'pytorch',
  weights_path: '/server/legacy.pt', metadata: {}, created_at: '2026-10-20T00:00:00Z' }
const registration = { silo_id: 'silo-01', label: '실서버 기관', base_url: 'tcp://silo-01:2375', collect_interval_seconds: 15 }
function response(url: string) {
  const value = url.endsWith('/api/models') ? [serverModel] : url.endsWith('/api/silos') ? [registration]
    : url.includes('/metrics?') ? { items: [], total: 0 } : []
  return new Response(JSON.stringify(value))
}

test('OFF→ON→OFF 이전 응답은 폐기하고 새 서버 응답은 이름과 무관하게 보존한다', async () => {
  let release!: () => void
  const wait = new Promise<void>((done) => { release = done })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => { await wait; return response(url) }))
  const { mode, models, silos } = await stores()
  const { pollLiveData } = await import('@/hooks/useLivePolling')
  const pending = pollLiveData()
  mode.getState().setMockEnabled(true)
  models.getState().setProjectFilter('프로젝트3')
  mode.getState().setMockEnabled(false)
  release()
  await pending
  expect(models.getState().models).toEqual([])
  expect(silos.getState().silos).toEqual([])
  await pollLiveData()
  expect(models.getState().models.map((m) => m.project)).toEqual([serverModel.name])
  expect(models.getState().projectFilter).toBe('all')
  expect(models.getState().models[0].accuracy).toBeNull()
  const { ModelRegistry } = await import('@/components/models/ModelRegistry')
  const actual = renderToStaticMarkup(<ModelRegistry />)
  expect(actual).toContain(serverModel.name)
  expect(actual).toContain('미수집')
  expect(silos.getState().silos[0].serverId).toBe('silo-01')
  expect(silos.getState().silos[0].cpu).toBeNull()
})

test('늦은 history/완료결과 조회는 모드 왕복 뒤 이전 선택 값을 복구하지 않는다', async () => {
  let release!: () => void
  const wait = new Promise<void>((done) => { release = done })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => { await wait; return new Response(JSON.stringify(url.includes('/resources/samples/') ? { items: [{ cpu_pct: 99 }] } : [])) }))
  const { mode, silos, models } = await stores()
  const history = silos.getState().loadHistory('silo-1')
  const catalog = models.getState().loadLiveModelResults()
  mode.getState().setMockEnabled(true)
  mode.getState().setMockEnabled(false)
  release()
  await Promise.all([history, catalog])
  expect(silos.getState().histories).toEqual({})
  expect(models.getState().liveModelResults).toEqual([])
})

test('API503·빈 응답은 fixture를 만들지 않고 다른 API의 실서버 기록을 유지한다', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/api/packaging')
    ? new Response('', { status: 503 }) : response(url)))
  const { mode, models, silos, data } = await stores()
  const { pollLiveData } = await import('@/hooks/useLivePolling')
  await pollLiveData()
  expect(mode.getState().liveStatus).toBe('error')
  const { DataSourceStatus } = await import('@/components/layout/DataSourceStatus')
  expect(renderToStaticMarkup(<DataSourceStatus />)).toContain('서버 조회 실패')
  expect(models.getState().models[0].project).toBe(serverModel.name)
  expect(silos.getState().silos[0].name).toBe('실서버 기관')
  expect(data.getState().jobs).toEqual([])
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.includes('/metrics?') ? { items: [], total: 0 } : []))))
  await pollLiveData()
  expect(mode.getState().liveStatus).toBe('empty')
  expect(renderToStaticMarkup(<DataSourceStatus />)).toContain('서버가 빈 목록을 반환')
  expect(models.getState().models).toEqual([])
  expect(silos.getState().silos).toEqual([])
  expect(data.getState().dataBySilo).toEqual({})
})
