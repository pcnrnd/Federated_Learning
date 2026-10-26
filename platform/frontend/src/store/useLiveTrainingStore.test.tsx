import '@/test/currentSnapshotSsr'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { TrainingJobApi, TrainingRoundSummary } from '@/api/client'
import { useSimulationStore } from '@/store/useSimulationStore'
import { useLiveTrainingStore as store } from './useLiveTrainingStore'
import { LiveTrainingScheduler } from '@/components/data/LiveTrainingScheduler'

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/client', () => ({ apiGet: get, apiPost: post, isLiveConfigured: () => true }))
const releases: Array<() => void> = []
const jobs: TrainingJobApi[] = [{ job_id: 'real-job', model_name: 'm', version: '1.0.0', status: 'active',
  rounds_completed: 1, max_rounds: 2, current_round_id: 'real-round' }]
const rounds: TrainingRoundSummary[] = [{ round_id: 'real-round', status: 'open', contributors: [], total_samples: 37 }]
const observe = () => { const release = store.getState().observe(); releases.push(release); return release }
function snapshot() { get.mockImplementation(async (path) => path === '/api/training-jobs' ? jobs : rounds) }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done }); return { promise, resolve } }

beforeEach(() => {
  vi.clearAllMocks()
  useSimulationStore.setState({ mockEnabled: false })
  store.setState({ jobs: [], rounds: [], error: null, pending: false, pollPending: false, observers: 0 })
  snapshot()
})
afterEach(() => { releases.splice(0).forEach((release) => release()); vi.restoreAllMocks() })

test('같은 store snapshot을 두 구독 화면이 공유하고 poll 실패는 이전 결과와 오류를 유지한다', async () => {
  observe(); observe()
  await vi.waitFor(() => expect(store.getState().pollPending).toBe(false))
  expect(get).toHaveBeenCalledTimes(2)
  expect(store.getState().jobs).toEqual(jobs)
  get.mockRejectedValue(new Error('HTTP 503'))
  expect(await store.getState().poll()).toBe(false)
  expect(store.getState()).toMatchObject({ jobs, rounds, error: 'HTTP 503', pollPending: false })
  const html = renderToStaticMarkup(<LiveTrainingScheduler />)
  expect(html).toContain('real-job')
  expect(html).toContain('real-round')
  expect(html).toContain('실제 표본 37')
  expect(html).toContain('HTTP 503')
})

test('mutation은 서버 완료 후 재조회하고 실패 시 snapshot을 보존한다', async () => {
  observe()
  await vi.waitFor(() => expect(store.getState().pollPending).toBe(false))
  post.mockResolvedValue({})
  expect(await store.getState().mutate('/api/training-jobs', { job_id: 'new' })).toBe(true)
  expect(post).toHaveBeenCalledWith('/api/training-jobs', { job_id: 'new' })
  expect(get).toHaveBeenCalledTimes(4)
  post.mockRejectedValue(new Error('HTTP 401'))
  expect(await store.getState().mutate('/api/training-jobs/real-job/pause')).toBe(false)
  expect(store.getState()).toMatchObject({ jobs, rounds, pending: false, error: 'HTTP 401' })
})

test('unmount 뒤 늦은 poll은 새 구독 snapshot을 덮어쓰지 않는다', async () => {
  const lateJobs = deferred<TrainingJobApi[]>(), lateRounds = deferred<TrainingRoundSummary[]>()
  get.mockImplementation((path) => path === '/api/training-jobs' ? lateJobs.promise : lateRounds.promise)
  const release = observe()
  release()
  snapshot()
  observe()
  await vi.waitFor(() => expect(store.getState().jobs).toEqual(jobs))
  lateJobs.resolve([{ ...jobs[0], job_id: 'stale' }]); lateRounds.resolve([])
  await Promise.all([lateJobs.promise, lateRounds.promise])
  await Promise.resolve()
  expect(store.getState()).toMatchObject({ jobs, rounds, pollPending: false })
})

test('mock 전환 뒤 늦은 mutation/조회는 성공 상태를 게시하지 않고 live 재개 시 재조회한다', async () => {
  observe()
  await vi.waitFor(() => expect(store.getState().pollPending).toBe(false))
  const late = deferred<unknown>()
  post.mockReturnValue(late.promise)
  const mutation = store.getState().mutate('/api/training-jobs/real-job/cancel')
  expect(store.getState().pending).toBe(true)
  useSimulationStore.setState({ mockEnabled: true })
  late.resolve({})
  expect(await mutation).toBe(false)
  expect(store.getState()).toMatchObject({ jobs: [], rounds: [], pending: false, pollPending: false, error: null })
  useSimulationStore.setState({ mockEnabled: false })
  await vi.waitFor(() => expect(store.getState().jobs).toEqual(jobs))
})

test('mutation이 오래된 poll을 무효화하고 중복 mutation을 거부한다', async () => {
  const lateJobs = deferred<TrainingJobApi[]>(), lateRounds = deferred<TrainingRoundSummary[]>()
  get.mockImplementation((path) => path === '/api/training-jobs' ? lateJobs.promise : lateRounds.promise)
  observe()
  const done = deferred<unknown>()
  post.mockReturnValue(done.promise)
  const mutation = store.getState().mutate('/api/training-jobs/real-job/pause')
  expect(await store.getState().mutate('/api/training-jobs/real-job/cancel')).toBe(false)
  snapshot(); done.resolve({})
  expect(await mutation).toBe(true)
  lateJobs.resolve([]); lateRounds.resolve([])
  await Promise.all([lateJobs.promise, lateRounds.promise]); await Promise.resolve()
  expect(store.getState()).toMatchObject({ jobs, rounds, pending: false, pollPending: false })
  expect(post).toHaveBeenCalledTimes(1)
})
