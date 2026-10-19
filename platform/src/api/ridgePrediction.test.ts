import { afterEach, expect, test, vi } from 'vitest'

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules() })

test('추론은 slash/percent/Unicode 모델명을 정확한 JSON 식별자로 전송한다', async () => {
  vi.stubEnv('VITE_API_BASE', 'http://central')
  const calls: unknown[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, body: JSON.parse(init.body as string) })
    return new Response(JSON.stringify({ predictions: [12] }))
  }))
  const { predictRegisteredRidge } = await import('./client')
  for (const name of ['기관/a', '기관%2Fa', '기관 공백:모델']) {
    await predictRegisteredRidge(name, '1.0.0', [[1, 2, 3]])
  }
  expect(calls).toEqual(['기관/a', '기관%2Fa', '기관 공백:모델'].map((name) => ({
    url: 'http://central/api/models/predict', body: { name, version: '1.0.0', inputs: [[1, 2, 3]] },
  })))
})
