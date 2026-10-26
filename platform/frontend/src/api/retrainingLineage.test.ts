import { afterEach, beforeEach, expect, test, vi } from 'vitest'

beforeEach(() => {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE', 'https://configured.example/base')
  vi.stubEnv('VITE_FED_API_KEY', 'test-access-key')
})
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals() })

test('세 계보는 정확한 endpoint와 원래 ID를 인증 client로 조회한다', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'completed',
    total_rows_in: 8, total_rows_out: 6, rounds_completed: 2, max_rounds: 2,
    format: 'ridge-v1', total_samples: 6, parameter_dim: 3, parameters: [123.456], target: 'private' }) })
  vi.stubGlobal('fetch', fetch)
  const { fetchLineage } = await import('./retrainingLineage')
  for (const kind of ['cleaning', 'training', 'result'] as const) {
    const lines = await fetchLineage(kind, '원본/ID@1')
    expect(JSON.stringify(lines)).not.toMatch(/123\.456|private|parameters/)
  }
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([
    'https://configured.example/base/api/cleaning-jobs/%EC%9B%90%EB%B3%B8%2FID%401',
    'https://configured.example/base/api/training-jobs/%EC%9B%90%EB%B3%B8%2FID%401',
    'https://configured.example/base/api/training-rounds/%EC%9B%90%EB%B3%B8%2FID%401/result',
  ])
  for (const [url, options] of fetch.mock.calls) {
    expect(url).not.toContain('test-access-key')
    expect(options.headers['X-FED-API-Key']).toBe('test-access-key')
    expect(options.method).toBeUndefined()
  }
})

test('조회 실패는 상세 오류로 표시하며 직접 URL이나 원시 응답을 저장하지 않는다', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))
  const { useRetrainingLineageStore: store } = await import('@/store/useRetrainingLineageStore')
  const { lineageKey } = await import('./retrainingLineage')
  await store.getState().load('cleaning', 'actual-clean')
  expect(store.getState().entries[lineageKey('cleaning', 'actual-clean')]).toEqual({ pending: false,
    lines: [], error: '상세 조회에 실패했습니다. 서버 연결과 접근 권한을 확인하세요.' })
})

test('모드 전환 뒤 도착한 계보 응답은 다시 LIVE여도 재사용하지 않는다', async () => {
  let resolve!: (value: unknown) => void
  const fetch = vi.fn().mockReturnValue(new Promise((done) => { resolve = done }))
  vi.stubGlobal('fetch', fetch)
  const { useSimulationStore: modes } = await import('@/store/useSimulationStore')
  const { useRetrainingLineageStore: store } = await import('@/store/useRetrainingLineageStore')
  const pending = store.getState().load('training', 'actual-train')
  modes.getState().setMockEnabled(true)
  modes.getState().setMockEnabled(false)
  resolve({ ok: true, json: async () => ({ status: 'completed', rounds_completed: 2, max_rounds: 2 }) })
  await pending
  expect(store.getState().entries).toEqual({})
  modes.getState().setMockEnabled(true)
  await store.getState().load('result', 'actual-round')
  expect(fetch).toHaveBeenCalledTimes(1)
})
