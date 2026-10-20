import '@/test/currentSnapshotSsr'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { RetrainingPanel } from '@/components/analytics/RetrainingPanel'
import { emptyRetrainingDraft } from '@/lib/retraining'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { RetrainingConfig, RetrainingEvent, RetrainingOverview } from '@/types/simulation'
import { useRetrainingStore as store } from './useRetrainingStore'

const { fetch, save, run, retry } = vi.hoisted(() => ({ fetch: vi.fn(), save: vi.fn(), run: vi.fn(), retry: vi.fn() }))
vi.mock('@/api/client', () => ({ isLiveConfigured: () => true }))
vi.mock('@/api/retraining', () => ({ fetchRetraining: fetch, saveRetraining: save, runRetraining: run, retryRetraining: retry }))
const config: RetrainingConfig = { retrain_config_id: 'c'.repeat(64), config_version: 3, definition: {
  config_id: 'a'.repeat(64), policy_id: 'b'.repeat(64), model_name: '실제 모델', version: '1.0.0',
  group_id: 'cohort', dataset_label: 'patients', max_rounds: 2, enabled: true, auto_enabled: false } }
const event: RetrainingEvent = { event_id: 'durable-event', retrain_config_id: config.retrain_config_id,
  status: 'training', automatic: false, error_code: null, created_at: '2026-10-20', updated_at: '2026-10-20',
  cleaning_request: { job_id: 'actual-clean' }, training_request: { job_id: 'actual-train', model_name: '실제 모델', version: '1.0.0' }, round_ids: [], registered_model: null }
const snapshot = (): RetrainingOverview => ({ configs: [config], events: [event], options: [{ config_id: config.definition.config_id,
  policy_id: config.definition.policy_id, model_name: '실제 모델', version: '1.0.0', feature: 'x' }], groups: [{ group_id: 'cohort', members: 2 }] })
const releases: Array<() => void> = []
const loaded = async () => { releases.push(store.getState().observe()); await vi.waitFor(() => expect(store.getState().polling).toBe(false)) }
const html = () => renderToStaticMarkup(<RetrainingPanel />)
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done }); return { promise, resolve } }

beforeEach(() => {
  vi.clearAllMocks()
  useSimulationStore.setState({ mockEnabled: false })
  store.setState({ snapshot: { configs: [], events: [], options: [], groups: [] }, draft: emptyRetrainingDraft(), dirty: false,
    desiredModel: null, selected: null, pending: false, polling: false, error: null, observers: 0, command: null })
  fetch.mockResolvedValue(snapshot()); save.mockResolvedValue(config); run.mockResolvedValue(event); retry.mockResolvedValue(event)
})
afterEach(() => { releases.splice(0).forEach((done) => done()); vi.restoreAllMocks() })

test('서버 학습 진행을 표시하고 새 모델 등록·경고 확인·운영 전환과 구분한다', async () => {
  await loaded()
  expect(html()).toContain('학습 진행')
  expect(html()).not.toContain('새 모델 등록 완료')
  expect(html()).toContain('경고 확인·해소와 새 모델 등록은 별도')
  fetch.mockResolvedValue({ ...snapshot(), events: [{ ...event, status: 'registered', registered_model: {
    name: '실제 모델', version: '1.0.1', weights_sha256: 'weights', result_id: 'real-result', round_id: 'last-round' } }] })
  await store.getState().poll()
  expect(html()).toContain('새 실험 모델 실제 모델@1.0.1 등록 완료')
  expect(html()).toContain('운영 전환은 별도')
})

test('응답 유실은 같은 수동 명령으로 재전송하고 새 명령은 새 ID를 쓴다', async () => {
  await loaded()
  run.mockRejectedValueOnce(new Error('ACK lost'))
  expect(await store.getState().run()).toBe(false)
  const first = run.mock.calls[0]
  expect(await store.getState().run()).toBe(true)
  expect(run.mock.calls[1]).toEqual(first)
  expect(await store.getState().run()).toBe(true)
  expect(run.mock.calls[2][1]).not.toBe(first[1])
})

test('POST 성공 뒤 GET 실패에도 accepted 명령과 오류를 보존하고 재조회 후만 회복한다', async () => {
  await loaded()
  fetch.mockRejectedValueOnce(new Error('HTTP 503'))
  expect(await store.getState().run()).toBe(false)
  const id = run.mock.calls[0][1]
  expect(store.getState().command?.requestId).toBe(id)
  expect(store.getState().error).toContain('503')
  expect(await store.getState().run()).toBe(true)
  expect(run.mock.calls[1][1]).toBe(id)
  expect(store.getState().error).toBeNull()
})

test('서버 commit 뒤 ACK 유실과 모드 왕복은 같은 의도를 한 이벤트로 재연결한다', async () => {
  await loaded()
  const server = new Map<string, RetrainingEvent>()
  run.mockImplementation(async (_config: string, requestId: string) => {
    if (!server.has(requestId)) {
      server.set(requestId, { ...event, event_id: 'one-event', request_id: requestId })
      throw new Error('server committed, ACK lost')
    }
    return server.get(requestId)
  })
  expect(await store.getState().run()).toBe(false)
  const command = store.getState().command
  useSimulationStore.setState({ mockEnabled: true })
  expect(store.getState().snapshot.events).toEqual([])
  expect(store.getState().command).toEqual(command)
  expect(await store.getState().run()).toBe(false)
  expect(run).toHaveBeenCalledTimes(1)
  useSimulationStore.setState({ mockEnabled: false })
  await vi.waitFor(() => expect(store.getState().polling).toBe(false))
  fetch.mockResolvedValue({ ...snapshot(), events: [...server.values()] })
  expect(await store.getState().resumeCommand()).toBe(true)
  expect(run.mock.calls[1]).toEqual(run.mock.calls[0])
  expect(server.size).toBe(1)
  expect(store.getState().command).toBeNull()
  run.mockResolvedValue({ ...event, event_id: 'explicit-new-event' })
  await store.getState().run()
  expect(run.mock.calls[2][1]).not.toBe(command!.requestId)
})

test('모드 전환 중 늦은 ACK는 화면을 채우지 않고 미확인 명령은 보존한다', async () => {
  await loaded()
  const post = deferred<RetrainingEvent>()
  run.mockReturnValue(post.promise)
  const action = store.getState().run()
  const command = store.getState().command
  useSimulationStore.setState({ mockEnabled: true })
  post.resolve(event)
  expect(await action).toBe(false)
  expect(store.getState().snapshot.events).toEqual([])
  expect(store.getState().command).toEqual(command)
  expect(store.getState().pending).toBe(false)
})

test('미확인 요청은 다른 설정 선택으로 덮어쓰지 않고 서버 확인 뒤에만 해소한다', async () => {
  await loaded()
  run.mockRejectedValueOnce(new Error('ACK lost'))
  await store.getState().run()
  const command = store.getState().command
  const other = { ...config, retrain_config_id: 'other-config' }
  store.setState({ snapshot: { ...snapshot(), configs: [other] }, selected: other.retrain_config_id, dirty: false })
  expect(await store.getState().run()).toBe(false)
  expect(store.getState().command).toEqual(command)
  expect(run).toHaveBeenCalledTimes(1)
})

test.each(['mode', 'unmount'])('늦은 설정 저장 응답은 %s 뒤 화면/명령을 되살리지 않는다', async (boundary) => {
  await loaded()
  const post = deferred<RetrainingConfig>()
  save.mockReturnValue(post.promise)
  store.getState().patch({ dataset: 'edited' })
  const action = store.getState().save()
  if (boundary === 'mode') useSimulationStore.setState({ mockEnabled: true })
  else releases.splice(0).forEach((done) => done())
  post.resolve({ ...config, retrain_config_id: 'late-config' })
  expect(await action).toBe(false)
  expect(store.getState().selected).not.toBe('late-config')
  expect(store.getState().pending).toBe(false)
})

test('draft와 기존 상세 학습/정제 설정을 유지하고 자동은 명시적 저장값만 전송한다', async () => {
  const advanced = { ...config, definition: { ...config.definition, learning: { l2: .2, step_size: .03, steps: 4 },
    worker_endpoints: { 'silo-1': 'http://silo-1:8081' } } }
  fetch.mockResolvedValue({ ...snapshot(), configs: [advanced] })
  await loaded()
  store.getState().patch({ automatic: true })
  await store.getState().poll()
  expect(store.getState().draft.automatic).toBe(true)
  await store.getState().save()
  expect(save.mock.calls[0][0]).toStrictEqual({ config_id: config.definition.config_id, policy_id: config.definition.policy_id,
    group_id: 'cohort', dataset_label: 'patients', max_rounds: 2, enabled: true,
    auto_enabled: true, learning: advanced.definition.learning, worker_endpoints: advanced.definition.worker_endpoints, cleaning: undefined })
})

test('모델 버튼의 대상 선택은 유효한 저장 설정을 찾고 실제 실행 전 확인을 요구한다', async () => {
  store.getState().focusModel('실제 모델', '1.0.0')
  await loaded()
  expect(store.getState().selected).toBe(config.retrain_config_id)
  expect(run).not.toHaveBeenCalled()
  expect(html()).toContain('저장한 설정으로 재교육')
})
