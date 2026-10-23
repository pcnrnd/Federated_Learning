import { afterEach, expect, test, vi } from 'vitest'
import { persistRetrainingCommand, readRetrainingCommand } from './retrainingCommand'

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs() })
test('새로고침용 저장값은 서버별 명령 ID만 보존하고 확인 후 제거한다', () => {
  const values = new Map<string, string>()
  vi.stubGlobal('window', { localStorage: { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) } })
  vi.stubEnv('VITE_API_BASE', 'https://one.example/api')
  const command = { configId: 'saved-config', requestId: 'same-request' }
  persistRetrainingCommand(command)
  expect(readRetrainingCommand()).toEqual(command)
  vi.stubEnv('VITE_API_BASE', 'https://two.example/api')
  expect(readRetrainingCommand()).toBeNull()
  vi.stubEnv('VITE_API_BASE', 'https://one.example/api')
  expect(readRetrainingCommand()).toEqual(command)
  persistRetrainingCommand(null)
  expect(readRetrainingCommand()).toBeNull()
})
