import '@/test/currentSnapshotSsr'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ModelVersion } from '@/types/simulation'

beforeEach(() => { vi.resetModules(); vi.stubEnv('VITE_API_BASE', 'http://central') })
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals() })

async function liveStore() {
  const { useSimulationStore } = await import('@/store/useSimulationStore')
  useSimulationStore.setState({ mockEnabled: false, log: vi.fn() })
  const { useModelStore } = await import('./useModelStore')
  useModelStore.getState().clearAll()
  return useModelStore
}

const model: ModelVersion = { id: 'placeholder', project: 'm', version: '1.0.1', status: 'experimental',
  accuracy: 0, algorithm: 'fedavg', rounds: 1, createdAt: '2026-10-19' }

test('registry 조회만으로 패키지를 built로 만들지 않는다', async () => {
  const store = await liveStore()
  store.getState().applyLiveModels([model], [])
  expect(store.getState().packages).toEqual({})
})

test('live 모델 재교육 버튼은 선택한 실제 모델의 설정 화면을 열고 가짜 새 버전을 만들지 않는다', async () => {
  const store = await liveStore()
  const { modelKey } = await import('@/api/mappers')
  const { useSimulationStore } = await import('@/store/useSimulationStore')
  const { useRetrainingStore } = await import('@/store/useRetrainingStore')
  const id = modelKey('m', '1.0.1')
  store.getState().applyLiveModels([{ ...model, id }], [])
  const before = store.getState().models
  store.getState().triggerRetrain(id)
  expect(store.getState().models).toBe(before)
  expect(useSimulationStore.getState().activeTab).toBe('analytics')
  expect(useRetrainingStore.getState().desiredModel).toBe(JSON.stringify(['m', '1.0.1']))
})

test('등록 401 실패는 기존 모델을 유지하고 화면 오류/대기 상태를 갱신한다', async () => {
  const store = await liveStore()
  store.getState().applyLiveModels([model], [])
  const before = store.getState().models
  store.getState().patchLiveModelDraft({ round_id: 'real-result' })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":"denied"}', { status: 401 })))
  expect(await store.getState().createLiveModel()).toBe(false)
  expect(store.getState().models).toBe(before)
  expect(store.getState().liveModelError).toContain('HTTP 401')
  expect(store.getState().liveModelPending).toBe(false)
})

test('실제 완료 결과를 등록한 뒤 서버 registry/package 조회를 반영한다', async () => {
  const writes: unknown[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') { writes.push(JSON.parse(init.body as string)); return new Response('{}') }
    const data = url.endsWith('/api/models') ? [{ name: 'm', version: '1.0.1', framework: 'ridge', weights_path: '/actual',
      metadata: { result_id: 'real-result' }, created_at: '2026-10-19T00:00:00Z' }]
      : url.endsWith('/api/packaging') ? [{ model_name: 'm', version: '1.0.1', status: 'unbuilt' }] : []
    return new Response(JSON.stringify(data))
  }))
  const store = await liveStore()
  store.getState().patchLiveModelDraft({ round_id: 'round-1' })
  expect(await store.getState().createLiveModel()).toBe(true)
  expect(writes).toEqual([{ round_id: 'round-1' }])
  expect(store.getState().models[0].resultId).toBe('real-result')
  expect(Object.values(store.getState().packages)[0].state).toBe('idle')
})

test('live 빌드는 서버 202/building을 유지하고 demo timer로 완료시키지 않는다', async () => {
  const { modelKey } = await import('@/api/mappers')
  const writes: Array<{ url: string; body: unknown }> = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') { writes.push({ url, body: JSON.parse(init.body as string) }); return new Response('{}', { status: 202 }) }
    const data = url.endsWith('/api/models') ? [{ name: 'm', version: '1.0.1', framework: 'ridge', weights_path: '/actual', metadata: {}, created_at: 'now' }]
      : url.endsWith('/api/packaging') ? [{ model_name: 'm', version: '1.0.1', status: 'building', image_tag: 'actual-tag' }] : []
    return new Response(JSON.stringify(data))
  }))
  const store = await liveStore()
  const id = modelKey('m', '1.0.1')
  store.getState().applyLiveModels([{ ...model, id }], [])
  store.getState().buildPackage(id, 'python:3.12-slim')
  await vi.waitFor(() => expect(store.getState().liveModelPending).toBe(false))
  expect(writes).toEqual([{ url: 'http://central/api/packaging/request', body: { model_name: 'm', version: '1.0.1', base_image: 'python:3.12-slim' } }])
  expect(store.getState().packages[id]).toMatchObject({ state: 'building', imageTag: 'actual-tag' })
})

test('완료 목록은 실제 ridge 결과만 선택 가능하게 하고 잘못된 결과는 제외한다', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify([
    { round_id: 'valid', status: 'completed', result: { format: 'ridge-v1', result_id: 'stored' } },
    { round_id: 'legacy', status: 'completed', result: null },
    { round_id: 'pending', status: 'open', result: { format: 'ridge-v1', result_id: 'not-ready' } },
  ]))))
  const store = await liveStore()
  await store.getState().loadLiveModelResults()
  expect(store.getState().liveModelResults.map((round) => round.round_id)).toEqual(['valid'])
})

test('live form과 package 실패 화면은 실제 원본/서버 오류를 표시한다', async () => {
  const store = await liveStore()
  store.setState({ liveModelError: '서버 가중치 무결성 실패' })
  const { LiveModelForm } = await import('@/components/models/LiveModelForm')
  const { PackagingCard } = await import('@/components/models/PackagingCard')
  const form = renderToStaticMarkup(<LiveModelForm onClose={() => undefined} />)
  expect(form).toContain('완료된 실제 학습 결과')
  expect(form).toContain('서버 가중치 무결성 실패')
  const card = renderToStaticMarkup(<PackagingCard model={model} pkg={{ modelId: model.id, state: 'failed',
    runtime: '', imageTag: '', error: '실제 빌드 실패' }} />)
  expect(card).toContain('빌드 실패')
  expect(card).toContain('미생성')
  expect(card).not.toContain('빌드됨')
})
