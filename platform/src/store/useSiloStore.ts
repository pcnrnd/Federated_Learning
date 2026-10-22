import { create } from 'zustand'
import { apiGet, apiMutation, apiPost, type Paginated, type ResourceLimit, type ResourceSampleApi, type ResourceUsageSummary, type SiloGroupApi, type SiloRegistrationApi } from '@/api/client'
import { mapRegisteredSilos, refreshSiloObservation, siloDraftKey } from '@/lib/siloResources'
import { SILO_SEEDS } from '@/constants/simulation'
import { createNode } from '@/lib/nodeFactory'
import { useDataStore } from '@/store/useDataStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import { dataSourceGuard } from '@/lib/dataSource'
import type { LogKind, Silo, SiloThresholds, ResourceHistoryMetric } from '@/types/simulation'

// 시드(SILO_SEEDS) 다음 id부터 신규 등록 사일로에 부여
let siloSeq = SILO_SEEDS.length + 1
const nextSiloId = (): number => siloSeq++

function logToConsole(kind: LogKind, message: string): void {
  useSimulationStore.getState().log(kind, message)
}

function actionTarget(silos: Silo[], key: string | number): Silo | undefined {
  return silos.find((silo) => typeof key === 'string'
    ? silo.serverId === key : !silo.serverId && silo.id === key)
}

const DEFAULT_THRESHOLDS: SiloThresholds = { cpu: 85, mem: 80, disk: 90 }

/** 사일로(SILO_SEEDS)의 리소스 관점 시드 — 학습/파이프라인과 동일한 id·이름 공유 */
function seedSilos(): Silo[] {
  return SILO_SEEDS.map((s) => ({
    id: s.id,
    name: s.name,
    endpoint: s.endpoint,
    collectIntervalSec: s.collectIntervalSec,
    cpu: s.cpu,
    mem: s.mem,
    disk: s.disk,
    thresholds: { ...DEFAULT_THRESHOLDS },
  }))
}

export type GroupNode = Silo & { serverId: string }

/** 그룹·시계열에서 고를 수 있는 사일로. 데모 시드는 서버 ID가 없어 실서버와 같은 `silo-N`을 붙인다. */
export function groupNodes(silos: readonly Silo[], demo: boolean): GroupNode[] {
  return demo
    ? silos.map((s) => ({ ...s, serverId: s.serverId ?? `silo-${s.id}` }))
    : silos.filter((s): s is GroupNode => typeof s.serverId === 'string')
}

/** 데모 그룹 — 실서버 그룹 응답과 같은 형태로 카드 레이아웃을 맞춘다 */
export const DEMO_SILO_GROUPS: readonly SiloGroupApi[] = [
  { group_id: 'all-silos', description: '전체 사일로', member_node_ids: SILO_SEEDS.map((s) => `silo-${s.id}`), aggregator_node_id: null },
  { group_id: 'region-north', description: '북부 권역', member_node_ids: ['silo-2', 'silo-3'], aggregator_node_id: 'silo-1' },
  { group_id: 'region-south', description: '남부 권역', member_node_ids: ['silo-5', 'silo-6'], aggregator_node_id: 'silo-4' },
]

const DEMO_SAMPLE_COUNT = 36
const DEMO_SAMPLE_START = Date.parse('2026-06-02T08:00:00Z')
const DEMO_SAMPLE_STEP_MS = 5 * 60_000
const DEMO_SCOPE = { cpu: 'cgroup', mem: 'cgroup', disk: 'cgroup', cpu_cores: 'cgroup', mem_used_bytes: 'cgroup' }

/** 데모 자원 시계열 — 사일로 시드 값을 중심으로 결정적으로 흔들리는 표본 */
export function demoResourceSamples(node: GroupNode | undefined): ResourceSampleApi[] {
  if (!node) return []
  const wave = (base: number | null, i: number, amp: number) =>
    base === null ? null : Math.max(0, Math.min(100, Math.round((base + amp * Math.sin(i / 3 + node.id)) * 10) / 10))
  return Array.from({ length: DEMO_SAMPLE_COUNT }, (_, i) => ({
    silo_id: node.serverId,
    timestamp: new Date(DEMO_SAMPLE_START + i * DEMO_SAMPLE_STEP_MS).toISOString(),
    cpu_pct: wave(node.cpu, i, 8), mem_pct: wave(node.mem, i, 4), disk_pct: wave(node.disk, i, 1),
    cpu_cores: node.cpu === null ? null : Math.round(node.cpu * 4) / 100,
    mem_used_bytes: node.mem === null ? null : Math.round(node.mem * 80) * 1048576,
    measurement_scope: DEMO_SCOPE,
  }))
}

export interface NewSiloInput {
  siloId?: string
  name: string
  endpoint: string
  collectIntervalSec: number
  /** 하위 노드를 매달 상위 사일로 id (1~12). 계층 깊이는 2단으로 제한된다 */
  parentId?: number
}

export interface SiloStore {
  silos: Silo[]
  addSilo: (input: NewSiloInput) => Promise<boolean>
  updateThreshold: (key: string | number, partial: Partial<SiloThresholds>) => Promise<boolean>
  removeSilo: (key: string | number) => Promise<boolean>
  groups: SiloGroupApi[]
  pending: boolean
  mutationEpoch: number
  mutationError: string | null
  pollError: string | null
  recordPollFailure: (error: string, now?: number) => void
  refreshObservationState: (now?: number) => void
  applyLiveSilos: (silos: Silo[], groups: SiloGroupApi[]) => void
  refreshLive: () => Promise<void>
  saveGroup: (group: SiloGroupApi, existing: boolean) => Promise<boolean>
  deleteGroup: (groupId: string) => Promise<boolean>
  histories: Record<string, ResourceSampleApi[]>
  historyErrors: Record<string, string | null>
  selectedHistorySilo: string | null
  historyMetric: ResourceHistoryMetric
  selectHistory: (siloId: string, metric?: ResourceHistoryMetric) => void
  loadHistory: (siloId: string) => Promise<void>
  thresholdDrafts: Record<string, SiloThresholds>
  editThreshold: (key: string | number, partial: Partial<SiloThresholds>) => void
  groupDraft: SiloGroupApi
  editingGroupId: string | null
  editGroup: (group: SiloGroupApi | null) => void
  patchGroup: (partial: Partial<SiloGroupApi>) => void
  registrationDraft: { name: string; siloId: string; endpoint: string; collectIntervalSec: number; parentId: number | '' }
  patchRegistration: (partial: Partial<SiloStore['registrationDraft']>) => void
  clearRegistration: () => void
  /** 목 off — 사일로 목록을 비운다 */
  clearAll: () => void
  /** 목 on — 초기 시드로 복원한다 */
  reseed: () => void
  /** 라이브 모드 — 서버 폴링 결과로 목록을 통째로 교체한다 */
  setSilos: (silos: Silo[]) => void
}

export const useSiloStore = create<SiloStore>((set, get) => ({
  silos: useSimulationStore.getState().mockEnabled ? seedSilos() : [],
  groups: [], pending: false, mutationEpoch: 0, mutationError: null, pollError: null,
  recordPollFailure: (pollError, now = Date.now()) => set((s) => ({ pollError,
    silos: s.silos.map((silo) => refreshSiloObservation(silo, now, true)) })),
  refreshObservationState: (now = Date.now()) => set((s) => ({
    silos: s.silos.map((silo) => refreshSiloObservation(silo, now, s.pollError !== null)) })),
  groupDraft: { group_id: '', description: '', member_node_ids: [], aggregator_node_id: null },
  editingGroupId: null,
  editGroup: (group) => set({ editingGroupId: group?.group_id ?? null, groupDraft: group ? { ...group, member_node_ids: [...group.member_node_ids] } : { group_id: '', description: '', member_node_ids: [], aggregator_node_id: null } }),
  patchGroup: (partial) => set((s) => ({ groupDraft: { ...s.groupDraft, ...partial } })),
  histories: {}, historyErrors: {}, selectedHistorySilo: null, historyMetric: 'cpu',
  thresholdDrafts: {},
  registrationDraft: { name: '', siloId: '', endpoint: '', collectIntervalSec: 15, parentId: '' },
  patchRegistration: (partial) => set((s) => ({ registrationDraft: { ...s.registrationDraft, ...partial } })),
  clearRegistration: () => set({ registrationDraft: { name: '', siloId: '', endpoint: '', collectIntervalSec: 15, parentId: '' } }),
  editThreshold: (key, partial) => {
    const draftKey = siloDraftKey(key)
    const thresholds = get().thresholdDrafts[draftKey] ?? actionTarget(get().silos, key)?.thresholds
    if (thresholds) set((s) => ({ thresholdDrafts: { ...s.thresholdDrafts, [draftKey]: { ...thresholds, ...partial } } }))
  },
  applyLiveSilos: (silos, groups) => { if (!get().pending) set({ silos, groups, pollError: null }) },
  refreshLive: async () => {
    const current = dataSourceGuard(false)
    if (!current()) return
    try {
      const [registrations, usage, limits, groups] = await Promise.all([
        apiGet<SiloRegistrationApi[]>('/api/silos'), apiGet<ResourceUsageSummary[]>('/api/resources/usage'),
        apiGet<ResourceLimit[]>('/api/resources/limits'), apiGet<SiloGroupApi[]>('/api/silo-groups'),
      ])
      if (!current()) return
      set({ silos: mapRegisteredSilos(registrations, usage, limits, groups), groups, pollError: null })
    } catch (error) {
      if (current()) {
        get().recordPollFailure(error instanceof Error ? error.message : String(error))
      }
      throw error
    }
  },
  saveGroup: async (group, existing) => {
    const current = dataSourceGuard(false)
    if (!current()) return false
    if (get().pending) return false
    set((s) => ({ pending: true, mutationError: null, mutationEpoch: s.mutationEpoch + 1 }))
    try {
      await apiMutation(existing ? 'PUT' : 'POST', existing ? `/api/silo-groups/${encodeURIComponent(group.group_id)}` : '/api/silo-groups', group)
      if (!current()) return false
      await get().refreshLive()
      if (!current()) return false
      return true
    } catch (error) {
      if (current()) set({ mutationError: error instanceof Error ? error.message : String(error) })
      return false
    } finally { if (current()) set({ pending: false }) }
  },
  deleteGroup: async (groupId) => {
    const current = dataSourceGuard(false)
    if (!current()) return false
    if (get().pending) return false
    set((s) => ({ pending: true, mutationError: null, mutationEpoch: s.mutationEpoch + 1 }))
    try {
      await apiMutation('DELETE', `/api/silo-groups/${encodeURIComponent(groupId)}`)
      if (!current()) return false
      await get().refreshLive()
      if (!current()) return false
      return true
    } catch (error) {
      if (current()) set({ mutationError: error instanceof Error ? error.message : String(error) })
      return false
    } finally { if (current()) set({ pending: false }) }
  },
  selectHistory: (selectedHistorySilo, historyMetric) => set((s) => ({ selectedHistorySilo, historyMetric: historyMetric ?? s.historyMetric })),
  loadHistory: async (siloId) => {
    const current = dataSourceGuard(false)
    if (!current()) return
    try {
      const result = await apiGet<Paginated<ResourceSampleApi>>(`/api/resources/samples/${encodeURIComponent(siloId)}?limit=500`)
      if (!current()) return
      set((s) => ({ histories: { ...s.histories, [siloId]: result.items }, historyErrors: { ...s.historyErrors, [siloId]: null } }))
    } catch (error) {
      if (current()) set((s) => ({ historyErrors: { ...s.historyErrors, [siloId]: error instanceof Error ? error.message : String(error) } }))
    }
  },

  clearAll: () => set((s) => ({ silos: [], groups: [], histories: {}, historyErrors: {}, selectedHistorySilo: null,
    groupDraft: { group_id: '', description: '', member_node_ids: [], aggregator_node_id: null }, editingGroupId: null,
    registrationDraft: { name: '', siloId: '', endpoint: '', collectIntervalSec: 15, parentId: '' },
    pending: false, mutationEpoch: s.mutationEpoch + 1, mutationError: null, pollError: null, thresholdDrafts: {} })),
  reseed: () => set((s) => ({ silos: seedSilos(), groups: [], histories: {}, historyErrors: {}, selectedHistorySilo: null,
    groupDraft: { group_id: '', description: '', member_node_ids: [], aggregator_node_id: null }, editingGroupId: null,
    registrationDraft: { name: '', siloId: '', endpoint: '', collectIntervalSec: 15, parentId: '' },
    pending: false, mutationEpoch: s.mutationEpoch + 1, mutationError: null, pollError: null, thresholdDrafts: {} })),
  setSilos: (silos) => set({ silos }),

  addSilo: async (input) => {
    const current = dataSourceGuard(false)
    if (!useSimulationStore.getState().mockEnabled) {
      if (get().pending) return false
      set((s) => ({ pending: true, mutationError: null, mutationEpoch: s.mutationEpoch + 1 }))
      try {
        await apiPost('/api/silos', { silo_id: input.siloId, label: input.name, base_url: input.endpoint, collect_interval_seconds: input.collectIntervalSec })
        if (!current()) return false
        await get().refreshLive()
        if (!current()) return false
        logToConsole('server', `[${input.name}] 서버 사일로 등록을 저장했습니다.`)
        return true
      } catch (error) {
        if (current()) set({ mutationError: error instanceof Error ? error.message : String(error) })
        return false
      } finally { if (current()) set({ pending: false }) }
    }
    const parent = get().silos.find((s) => s.id === input.parentId)
    if (!parent) {
      logToConsole('error', '상위 사일로를 찾을 수 없어 하위 노드 등록을 취소했습니다.')
      return false
    }
    // 계층 깊이 2단 제한 — 하위 노드 밑에 다시 하위를 매달 수 없다
    if (parent.parentId !== undefined) {
      logToConsole('error', `[${parent.name}]은(는) 하위 노드이므로 그 아래에 다시 증설할 수 없습니다.`)
      return false
    }

    const silo: Silo = {
      id: nextSiloId(),
      name: input.name.trim(),
      endpoint: input.endpoint.trim(),
      collectIntervalSec: input.collectIntervalSec,
      // 신규 등록 노드는 초기 수집 전이므로 0에서 시작
      cpu: 0,
      mem: 0,
      disk: 0,
      thresholds: { ...DEFAULT_THRESHOLDS },
      parentId: input.parentId,
    }
    set((state) => ({ silos: [...state.silos, silo] }))
    // 데이터 파이프라인 탭에도 신규 노드가 나타나도록 전파
    useDataStore.getState().ensureSiloData(silo.id)
    // 학습 런타임에도 HFL 하위 참여자로 전파 (다음 라운드부터 학습 참여)
    useSimulationStore
      .getState()
      .addNode(
        createNode({
          id: silo.id,
          name: silo.name,
          shortName: silo.name,
          parentId: silo.parentId,
        }),
      )
    logToConsole(
      'server',
      `[${silo.name}] 하위 노드를 [${parent.name}] 아래에 증설했습니다. (${silo.endpoint}, 수집주기 ${silo.collectIntervalSec}s)`,
    )
    return true
  },

  updateThreshold: async (key, partial) => {
    const current = dataSourceGuard(false)
    const target = actionTarget(get().silos, key)
    if (!target) return false
    if (!useSimulationStore.getState().mockEnabled) {
      if (!target.serverId || get().pending) return false
      set((s) => ({ pending: true, mutationError: null, mutationEpoch: s.mutationEpoch + 1 }))
      const thresholds = { ...target.thresholds, ...partial }
      try {
        await apiPost('/api/resources/limits', { silo_id: target.serverId, cpu_pct_max: thresholds.cpu, mem_pct_max: thresholds.mem, disk_pct_max: thresholds.disk, gpu_pct_max: target.gpuThreshold ?? null })
        if (!current()) return false
        await get().refreshLive()
        if (!current()) return false
        set((s) => { const drafts = { ...s.thresholdDrafts }; delete drafts[siloDraftKey(key)]; return { thresholdDrafts: drafts } })
        return true
      } catch (error) {
        if (current()) set({ mutationError: error instanceof Error ? error.message : String(error) })
        return false
      } finally { if (current()) set({ pending: false }) }
    }
    set((state) => ({
      silos: state.silos.map((s) =>
        s.id === key ? { ...s, thresholds: { ...s.thresholds, ...partial } } : s,
      ),
    }))
    logToConsole('system', `[${target.name}] 리소스 임계값을 갱신했습니다.`)
    return true
  },

  removeSilo: async (key) => {
    const current = dataSourceGuard(false)
    const target = actionTarget(get().silos, key)
    if (!target) return false
    if (!useSimulationStore.getState().mockEnabled) {
      if (!target.serverId || get().pending) return false
      set((s) => ({ pending: true, mutationError: null, mutationEpoch: s.mutationEpoch + 1 }))
      try {
        await apiMutation('DELETE', `/api/silos/${encodeURIComponent(target.serverId)}`)
        if (!current()) return false
        await get().refreshLive()
        if (!current()) return false
        return true
      } catch (error) {
        if (current()) set({ mutationError: error instanceof Error ? error.message : String(error) })
        return false
      } finally { if (current()) set({ pending: false }) }
    }
    // 1단 사일로는 연합 구조의 고정 참여자 — 하위 노드만 해제할 수 있다
    if (target.parentId === undefined) {
      logToConsole('error', `[${target.name}]은(는) 1단 사일로이므로 해제할 수 없습니다.`)
      return false
    }
    set((state) => ({ silos: state.silos.filter((s) => s.id !== target.id) }))
    useDataStore.getState().removeSiloData(target.id)
    useSimulationStore.getState().removeNode(target.id)
    logToConsole('error', `[${target.name}] 하위 노드 등록을 해제했습니다.`)
    return true
  },
}))

useSimulationStore.subscribe((state, previous) => {
  if (state.mockEnabled !== previous.mockEnabled) {
    if (state.mockEnabled) useSiloStore.getState().reseed()
    else useSiloStore.getState().clearAll()
  }
})
