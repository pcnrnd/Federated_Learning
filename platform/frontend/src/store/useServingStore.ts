import { create } from 'zustand'
import { apiGet, apiMutation, isLiveConfigured } from '@/api/client'
import { newDeploymentRequestId } from '@/lib/deploymentRequests'
import { useSimulationStore } from './useSimulationStore'
import type { ServingComparison, ServingEvent, ServingGate, ServingRoute, ServingShadow } from '@/types/simulation'

interface ServingState {
  routes: ServingRoute[]
  shadows: ServingShadow[]
  selected: string | null
  comparison: ServingComparison | null
  events: ServingEvent[]
  error: string | null
  pending: boolean
  generation: number
  pollSequence: number
  shadowRequest: { fingerprint: string; requestId: string } | null
  lastResponse: { request_id: string; deployment_id: string; version: string; input_count: number } | null
  clear: () => void
  select: (identity: string) => void
  poll: () => Promise<boolean>
  create: (deploymentId: string) => Promise<boolean>
  shadow: (version: string, mirrorPct: number) => Promise<boolean>
  gate: (value: ServingGate) => Promise<boolean>
  action: (name: 'promote' | 'rollback' | 'close' | 'cleanup') => Promise<boolean>
  predict: (inputs: unknown[]) => Promise<boolean>
  shadowAction: (identity: string, name: 'retry' | 'abort') => Promise<boolean>
}

function live() { return !useSimulationStore.getState().mockEnabled && isLiveConfigured() }

async function mutate(path: string, body?: unknown, method: 'POST' | 'PUT' = 'POST'): Promise<boolean> {
  if (!live() || useServingStore.getState().pending) return false
  useServingStore.setState((state) => ({ pending: true, error: null, generation: state.generation + 1 }))
  const epoch = useServingStore.getState().generation
  const current = () => live() && epoch === useServingStore.getState().generation
  try {
    const response = await apiMutation<Record<string, unknown>>(method, path, body)
    if (!current()) return false
    if (path.endsWith('/predict')) useServingStore.setState({ lastResponse: {
      request_id: String(response.request_id), deployment_id: String(response.deployment_id),
      version: String(response.version), input_count: Number(response.input_count),
    } }) // 예측 값/입력은 저장·로그하지 않는다.
    const refreshed = await useServingStore.getState().poll()
    return current() && refreshed
  } catch (error) {
    if (current()) useServingStore.setState({ error: error instanceof Error ? error.message : '실제 route 요청 실패' })
    return false
  } finally {
    if (current()) useServingStore.setState({ pending: false })
  }
}

export const useServingStore = create<ServingState>((set, get) => ({
  routes: [], shadows: [], selected: null, comparison: null, events: [], error: null, pending: false, generation: 0,
  pollSequence: 0, shadowRequest: null, lastResponse: null,
  clear: () => set((state) => ({ routes: [], shadows: [], selected: null, comparison: null, events: [], error: null,
    pending: false, shadowRequest: null, lastResponse: null, generation: state.generation + 1, pollSequence: state.pollSequence + 1 })),
  select: (identity) => {
    set((state) => ({ selected: identity, comparison: null, events: [], error: null, lastResponse: null,
      generation: state.generation + 1, pending: false }))
    void get().poll()
  },
  poll: async () => {
    if (!live()) return false
    const epoch = get().generation
    const seq = get().pollSequence + 1
    set({ pollSequence: seq })
    const current = () => live() && epoch === get().generation && seq === get().pollSequence
    try {
      const [routes, shadows] = await Promise.all([apiGet<ServingRoute[]>('/api/serving-routes'),
        apiGet<ServingShadow[]>('/api/shadow-deployments')])
      if (!current()) return false
      const selected = routes.some((route) => route.route_id === get().selected) ? get().selected : routes[0]?.route_id ?? null
      const [comparison, events]: [ServingComparison | null, ServingEvent[]] = selected ? await Promise.all([
        apiGet<ServingComparison>(`/api/serving-routes/${selected}/comparison`),
        apiGet<ServingEvent[]>(`/api/serving-routes/${selected}/events`),
      ]) : [null, []]
      if (!current()) return false
      set({ routes, shadows, selected, comparison, events, error: null })
      return true
    } catch (error) {
      if (current()) set({ error: error instanceof Error ? error.message : '실제 route 조회 실패' })
      return false
    }
  },
  create: (deploymentId) => mutate('/api/serving-routes', { primary_deployment_id: deploymentId }),
  shadow: async (version, mirrorPct) => {
    if (!live() || get().pending) return false
    const route = get().routes.find((value) => value.route_id === get().selected)
    if (!route) return false
    const payload = { route_id: route.route_id, primary_deployment_id: route.primary_deployment_id,
      shadow_version: version, traffic_mirror_pct: mirrorPct }
    const fingerprint = JSON.stringify(payload)
    const requestId = get().shadowRequest?.fingerprint === fingerprint ? get().shadowRequest!.requestId : newDeploymentRequestId()
    set({ shadowRequest: { fingerprint, requestId } })
    const result = await mutate('/api/shadow-deployments', { ...payload, request_id: requestId })
    if (result && get().shadowRequest?.requestId === requestId) set({ shadowRequest: null })
    return result
  },
  gate: (value) => get().selected ? mutate(`/api/serving-routes/${get().selected}/gate`, value, 'PUT') : Promise.resolve(false),
  action: (name) => get().selected ? mutate(`/api/serving-routes/${get().selected}/${name}`) : Promise.resolve(false),
  predict: (inputs) => get().selected ? mutate(`/api/serving-routes/${get().selected}/predict`, {
    inputs, request_id: newDeploymentRequestId(),
  }) : Promise.resolve(false),
  shadowAction: (identity, name) => mutate(`/api/shadow-deployments/${identity}/${name}`),
}))

useSimulationStore.subscribe((state, previous) => {
  if (state.mockEnabled !== previous.mockEnabled) useServingStore.getState().clear()
})
