/** CSR 화면의 현재 store snapshot을 정적 SSR 단언에서도 읽게 하는 테스트 전용 harness. */
import { vi } from 'vitest'
import type { StateCreator } from 'zustand'

vi.mock('zustand', async (importOriginal) => {
  const actual = await importOriginal<typeof import('zustand')>()
  function createCurrentSnapshot<T>(initializer: StateCreator<T>) {
    return actual.create<T>((set, get, api) => {
      const state = initializer(set, get, api)
      // bound hook의 사후 spy가 아니라 React hook이 닫아 둔 vanilla api 자체를 생성 시 설정한다.
      api.getInitialState = api.getState
      return state
    })
  }
  const create = ((initializer?: StateCreator<unknown>) => (
    initializer === undefined ? createCurrentSnapshot : createCurrentSnapshot(initializer)
  )) as typeof actual.create
  return { ...actual, create }
})
