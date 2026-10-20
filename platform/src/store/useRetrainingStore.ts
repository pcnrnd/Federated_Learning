import { create } from 'zustand'
import { isLiveConfigured } from '@/api/client'
import { fetchRetraining, retryRetraining, runRetraining, saveRetraining } from '@/api/retraining'
import { emptyRetrainingDraft, retrainingDraft, retrainingPayload, type RetrainingDraft } from '@/lib/retraining'
import { persistRetrainingCommand, readRetrainingCommand, type PendingRetrainingCommand } from '@/lib/retrainingCommand'
import type { RetrainingOverview } from '@/types/simulation'
import { useSimulationStore } from './useSimulationStore'

interface RetrainingStore {
  snapshot: RetrainingOverview
  draft: RetrainingDraft
  dirty: boolean
  desiredModel: string | null
  selected: string | null
  pending: boolean
  polling: boolean
  error: string | null
  generation: number
  observers: number
  command: PendingRetrainingCommand | null
  observe: () => () => void
  poll: () => Promise<boolean>
  patch: (patch: Partial<RetrainingDraft>) => void
  select: (configId: string) => void
  focusModel: (name: string, version: string) => void
  save: () => Promise<boolean>
  run: () => Promise<boolean>
  resumeCommand: () => Promise<boolean>
  retry: (eventId: string) => Promise<boolean>
}

const blank = (): RetrainingOverview => ({ configs: [], events: [], options: [], groups: [] })
const live = () => isLiveConfigured() && !useSimulationStore.getState().mockEnabled
const modelKey = (name: string, version: string) => JSON.stringify([name, version])
let timer: ReturnType<typeof setInterval> | undefined
let unsubscribe: (() => void) | undefined
const current = (generation: number) => live() && useRetrainingStore.getState().observers > 0 && useRetrainingStore.getState().generation === generation

function invalidate(clear = false) {
  useRetrainingStore.setState((s) => ({ generation: s.generation + 1, pending: false, polling: false,
    ...(clear ? { snapshot: blank(), selected: null, error: null, draft: emptyRetrainingDraft(), dirty: false, desiredModel: null } : {}) }))
}

async function mutation(action: (epoch: number) => Promise<unknown>): Promise<boolean> {
  const store = useRetrainingStore
  if (!live() || !store.getState().observers || store.getState().pending) return false
  invalidate()
  const epoch = store.getState().generation
  store.setState({ pending: true }) // POST는 이전 조회 오류를 해소하지 않는다.
  try {
    await action(epoch)
    if (!current(epoch)) return false
    store.setState({ pending: false })
    return await store.getState().poll()
  } catch (error) {
    if (current(epoch)) store.setState({ error: error instanceof Error ? error.message : '재교육 요청 실패' })
    return false
  } finally {
    if (current(epoch)) store.setState({ pending: false })
  }
}

export const useRetrainingStore = create<RetrainingStore>((set, get) => ({
  snapshot: blank(), draft: emptyRetrainingDraft(), dirty: false, desiredModel: null, selected: null,
  pending: false, polling: false, error: null, generation: 0, observers: 0, command: readRetrainingCommand(),
  observe: () => {
    set((s) => ({ observers: s.observers + 1 }))
    if (get().observers === 1) {
      unsubscribe = useSimulationStore.subscribe((n, p) => { if (n.mockEnabled !== p.mockEnabled) { invalidate(true); if (!n.mockEnabled) void get().poll() } })
      timer = setInterval(() => { void get().poll() }, 5000)
      void get().poll()
    }
    let done = false
    return () => { if (done) return; done = true; set((s) => ({ observers: Math.max(0, s.observers - 1) }))
      if (!get().observers) { clearInterval(timer); timer = undefined; unsubscribe?.(); unsubscribe = undefined; invalidate() } }
  },
  poll: async () => {
    if (!live() || !get().observers || get().pending || get().polling) return false
    const epoch = get().generation
    set({ polling: true })
    try {
      const snapshot = await fetchRetraining()
      if (!current(epoch)) return false
      const desired = get().desiredModel
      const eligible = snapshot.configs.filter((c) => !desired || modelKey(c.definition.model_name, c.definition.version) === desired)
      const selected = get().dirty && get().selected === null ? undefined
        : eligible.find((c) => c.retrain_config_id === get().selected) ?? eligible[0]
      const option = snapshot.options.find((o) => !desired || modelKey(o.model_name, o.version) === desired)
      const changed = (selected?.retrain_config_id ?? null) !== get().selected
      const command = get().command
      set({ snapshot, error: null, selected: selected?.retrain_config_id ?? null,
        ...(!get().dirty || changed ? { draft: selected ? retrainingDraft(selected) : { ...emptyRetrainingDraft(), configId: option?.config_id ?? '' }, dirty: false } : {}),
        ...(command && snapshot.events.some((e) => e.event_id === command.acceptedEventId
          || e.request_id === command.requestId && e.retrain_config_id === command.configId) ? { command: null } : {}) })
      return true
    } catch (error) {
      if (current(epoch)) set({ error: error instanceof Error ? error.message : '재교육 상태 조회 실패' })
      return false
    } finally { if (current(epoch)) set({ polling: false }) }
  },
  patch: (patch) => set((s) => ({ draft: { ...s.draft, ...patch }, dirty: true })),
  select: (configId) => { if (get().pending) return
    if (!configId) { invalidate(); set({ selected: null, desiredModel: null, draft: emptyRetrainingDraft(), dirty: true }); return }
    const config = get().snapshot.configs.find((c) => c.retrain_config_id === configId)
    if (config) { invalidate(); set({ selected: configId, desiredModel: null, draft: retrainingDraft(config), dirty: false }) } },
  focusModel: (name, version) => { invalidate(); set({ desiredModel: modelKey(name, version), selected: null, dirty: false }); void get().poll() },
  save: async () => {
    const body = retrainingPayload(get().draft, get().snapshot.options)
    if (!body) { set({ error: '대상 정책·그룹·데이터셋과 2~100 라운드를 확인하세요.' }); return false }
    const prior = get().snapshot.configs.find((c) => c.retrain_config_id === get().selected)?.definition
    if (prior?.config_id === body.config_id) {
      body.cleaning = prior.cleaning; body.learning = prior.learning; body.worker_endpoints = prior.worker_endpoints
    }
    return mutation(async (epoch) => { const config = await saveRetraining(body)
      if (current(epoch)) set({ selected: config.retrain_config_id, draft: retrainingDraft(config), dirty: false, desiredModel: null }) })
  },
  run: () => {
    const config = get().snapshot.configs.find((c) => c.retrain_config_id === get().selected)
    if (!config?.definition.enabled || get().dirty) return Promise.resolve(false)
    if (!live() || !get().observers || get().pending) return Promise.resolve(false)
    if (get().command && get().command!.configId !== config.retrain_config_id) {
      set({ error: '미확인 재교육 요청이 있습니다. 이전 요청을 먼저 확인하세요.' })
      return Promise.resolve(false)
    }
    if (!get().command) set({ command: { configId: config.retrain_config_id, requestId: crypto.randomUUID() } })
    return get().resumeCommand()
  },
  resumeCommand: () => mutation(async (epoch) => {
    const command = get().command
    if (!command) return
    const event = await runRetraining(command.configId, command.requestId)
    if (current(epoch)) set({ command: { ...command, acceptedEventId: event.event_id } })
  }),
  retry: (eventId) => mutation(() => retryRetraining(eventId)),
}))

useRetrainingStore.subscribe((state, previous) => {
  if (state.command !== previous.command) persistRetrainingCommand(state.command)
})
useSimulationStore.subscribe((state, previous) => {
  if (state.mockEnabled !== previous.mockEnabled && !useRetrainingStore.getState().observers) invalidate(true)
})
