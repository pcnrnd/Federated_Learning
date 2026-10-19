import { create } from 'zustand'
import { apiGet, apiPost, isLiveConfigured, type TrainingJobApi, type TrainingRoundSummary } from '@/api/client'
import { useSimulationStore } from '@/store/useSimulationStore'

interface LiveTrainingState {
  jobs: TrainingJobApi[]
  rounds: TrainingRoundSummary[]
  error: string | null
  pending: boolean
  pollPending: boolean
  generation: number
  observers: number
  observe: () => () => void
  poll: () => Promise<boolean>
  mutate: (path: string, body?: unknown) => Promise<boolean>
}

let timer: ReturnType<typeof setInterval> | undefined
let unsubscribeMode: (() => void) | undefined
const live = () => isLiveConfigured() && !useSimulationStore.getState().mockEnabled
const current = (generation: number) => live() && useLiveTrainingStore.getState().observers > 0
  && useLiveTrainingStore.getState().generation === generation
const message = (reason: unknown) => reason instanceof Error ? reason.message : String(reason)

function invalidate(clearSnapshot = false) {
  useLiveTrainingStore.setState((state) => ({ generation: state.generation + 1,
    pending: false, pollPending: false, ...(clearSnapshot ? { jobs: [], rounds: [], error: null } : {}) }))
}

export const useLiveTrainingStore = create<LiveTrainingState>((set, get) => ({
  jobs: [], rounds: [], error: null, pending: false, pollPending: false, generation: 0, observers: 0,
  observe: () => {
    set((state) => ({ observers: state.observers + 1 }))
    if (get().observers === 1) {
      unsubscribeMode = useSimulationStore.subscribe((next, previous) => {
        if (next.mockEnabled === previous.mockEnabled) return
        invalidate(true)
        if (!next.mockEnabled) void get().poll()
      })
      timer = setInterval(() => { void get().poll() }, 5000)
      void get().poll()
    }
    let released = false
    return () => {
      if (released) return
      released = true
      set((state) => ({ observers: Math.max(0, state.observers - 1) }))
      if (get().observers === 0) {
        clearInterval(timer)
        timer = undefined
        unsubscribeMode?.()
        unsubscribeMode = undefined
        invalidate()
      }
    }
  },
  poll: async () => {
    if (!live() || !get().observers || get().pending || get().pollPending) return false
    const generation = get().generation
    set({ pollPending: true })
    try {
      const [jobs, rounds] = await Promise.all([apiGet<TrainingJobApi[]>('/api/training-jobs'),
        apiGet<TrainingRoundSummary[]>('/api/training-rounds')])
      if (!current(generation)) return false
      set({ jobs, rounds, error: null })
      return true
    } catch (reason) {
      if (current(generation)) set({ error: message(reason) })
      return false
    } finally {
      if (current(generation)) set({ pollPending: false })
    }
  },
  mutate: async (path, body) => {
    if (!live() || !get().observers || get().pending) return false
    invalidate()
    const generation = get().generation
    set({ pending: true, error: null })
    try {
      await apiPost(path, body)
      if (!current(generation)) return false
      set({ pending: false })
      return await get().poll()
    } catch (reason) {
      if (current(generation)) set({ error: message(reason) })
      return false
    } finally {
      if (current(generation)) set({ pending: false })
    }
  },
}))
