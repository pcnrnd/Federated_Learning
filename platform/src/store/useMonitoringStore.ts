import { create } from 'zustand'
import { DRIFT_ALERT, DRIFT_WARN } from '@/constants/simulation'
import { isLiveConfigured } from '@/api/client'
import { acknowledgeDistributionAlert, chooseDistributionBaseline, fetchDistributionOverview, persistDistributionPolicy } from '@/api/distributions'
import { draftForPolicy, driftScopeKey, emptyDriftDraft, parseDriftDraft, type DriftPolicyDraft } from '@/lib/distributionDrift'
import type { DistributionConfig, DistributionAlert, DriftObservation } from '@/types/simulation'
import { useSimulationStore } from './useSimulationStore'

/** 0~100 범위로 임계치를 클램프한다. */
function clampPct(value: number): number {
  return Math.min(100, Math.max(0, value))
}

export interface MonitoringStore {
  /** 경고 임계치 (0~100%) */
  warnThreshold: number
  /** 경보 임계치 (0~100%) */
  alertThreshold: number
  /** 드리프트 경보 시 자동 재학습 */
  autoRetrain: boolean
  /** 재학습 대상 모델 id; 'auto' = 첫 번째 배포 모델 */
  retrainModelId: string | 'auto'
  /** 설정 패널 펼침 여부 (기본 접힘) */
  settingsExpanded: boolean
  /** 자동 재학습이 마지막으로 발생한 라운드 (라운드당 1회 제한) */
  lastAutoRetrainRound: number | null

  setWarnThreshold: (pct: number) => void
  setAlertThreshold: (pct: number) => void
  setAutoRetrain: (enabled: boolean) => void
  setRetrainModelId: (id: string | 'auto') => void
  toggleSettingsExpanded: () => void
  setLastAutoRetrainRound: (round: number) => void
  liveConfigs: DistributionConfig[]
  liveRows: DriftObservation[]
  liveAlerts: DistributionAlert[]
  selectedScope: string | null
  policyDraft: DriftPolicyDraft
  draftDirty: boolean
  liveError: string | null
  livePending: boolean
  pollPending: boolean
  generation: number
  observers: number
  observeLive: () => () => void
  pollLive: () => Promise<boolean>
  selectLiveScope: (key: string) => void
  setPolicyDraft: (key: keyof DriftPolicyDraft, value: string) => void
  saveLivePolicy: () => Promise<boolean>
  chooseLiveBaseline: () => Promise<boolean>
  ackLiveAlert: (alertId: string) => Promise<boolean>
}

let timer: ReturnType<typeof setInterval> | undefined
let unsubscribe: (() => void) | undefined
const live = () => isLiveConfigured() && !useSimulationStore.getState().mockEnabled
const current = (epoch: number) => live() && useMonitoringStore.getState().observers > 0
  && epoch === useMonitoringStore.getState().generation

function invalidate(clear = false) {
  useMonitoringStore.setState((state) => ({ generation: state.generation + 1, livePending: false, pollPending: false,
    ...(clear ? { liveConfigs: [], liveRows: [], liveAlerts: [], selectedScope: null, liveError: null,
      policyDraft: emptyDriftDraft(), draftDirty: false } : {}) }))
}

async function mutate(action: () => Promise<unknown>, resetDraft = false): Promise<boolean> {
  const store = useMonitoringStore
  if (!live() || !store.getState().observers || store.getState().livePending) return false
  invalidate()
  const epoch = store.getState().generation
  // 마지막 조회 실패는 POST 시작/성공으로 해소되지 않는다. 새 GET 성공만 snapshot을 회복한다.
  store.setState({ livePending: true })
  try {
    await action()
    if (!current(epoch)) return false
    store.setState({ livePending: false, ...(resetDraft ? { draftDirty: false } : {}) })
    return await store.getState().pollLive()
  } catch (reason) {
    if (current(epoch)) store.setState({ liveError: reason instanceof Error ? reason.message : '분포 설정 요청 실패' })
    return false
  } finally {
    if (current(epoch)) store.setState({ livePending: false })
  }
}

export const useMonitoringStore = create<MonitoringStore>((set, get) => ({
  warnThreshold: DRIFT_WARN * 100,
  alertThreshold: DRIFT_ALERT * 100,
  autoRetrain: false,
  retrainModelId: 'auto',
  settingsExpanded: false,
  lastAutoRetrainRound: null,

  setWarnThreshold: (pct) => set({ warnThreshold: clampPct(pct) }),
  setAlertThreshold: (pct) => set({ alertThreshold: clampPct(pct) }),
  setAutoRetrain: (autoRetrain) => set({ autoRetrain }),
  setRetrainModelId: (retrainModelId) => set({ retrainModelId }),
  toggleSettingsExpanded: () => set((s) => ({ settingsExpanded: !s.settingsExpanded })),
  setLastAutoRetrainRound: (round) => set({ lastAutoRetrainRound: round }),
  liveConfigs: [], liveRows: [], liveAlerts: [], selectedScope: null, policyDraft: emptyDriftDraft(), draftDirty: false,
  liveError: null, livePending: false, pollPending: false, generation: 0, observers: 0,
  observeLive: () => {
    set((state) => ({ observers: state.observers + 1 }))
    if (get().observers === 1) {
      unsubscribe = useSimulationStore.subscribe((next, previous) => {
        if (next.mockEnabled === previous.mockEnabled) return
        invalidate(true)
        if (!next.mockEnabled) void get().pollLive()
      })
      timer = setInterval(() => { void get().pollLive() }, 5000)
      void get().pollLive()
    }
    let released = false
    return () => {
      if (released) return
      released = true
      set((state) => ({ observers: Math.max(0, state.observers - 1) }))
      if (!get().observers) {
        clearInterval(timer); timer = undefined; unsubscribe?.(); unsubscribe = undefined
        invalidate()
      }
    }
  },
  pollLive: async () => {
    if (!live() || !get().observers || get().livePending || get().pollPending) return false
    const epoch = get().generation
    set({ pollPending: true })
    try {
      const snapshot = await fetchDistributionOverview()
      if (!current(epoch)) return false
      const selected = snapshot.items.find((row) => driftScopeKey(row) === get().selectedScope) ?? snapshot.items[0]
      const selectionChanged = (selected ? driftScopeKey(selected) : null) !== get().selectedScope
      set({ liveConfigs: snapshot.configs, liveRows: snapshot.items, liveAlerts: snapshot.alerts,
        selectedScope: selected ? driftScopeKey(selected) : null, liveError: null,
        ...(!get().draftDirty || selectionChanged ? { policyDraft: draftForPolicy(selected?.policy ?? null), draftDirty: false } : {}) })
      return true
    } catch (reason) {
      if (current(epoch)) set({ liveError: reason instanceof Error ? reason.message : '실제 분포 조회 실패' })
      return false
    } finally {
      if (current(epoch)) set({ pollPending: false })
    }
  },
  selectLiveScope: (key) => {
    if (get().livePending) return
    const row = get().liveRows.find((value) => driftScopeKey(value) === key)
    if (!row) return
    invalidate()
    set({ selectedScope: key, policyDraft: draftForPolicy(row.policy), draftDirty: false })
    void get().pollLive()
  },
  setPolicyDraft: (key, value) => set((state) => ({ policyDraft: { ...state.policyDraft, [key]: value }, draftDirty: true })),
  saveLivePolicy: () => {
    const row = get().liveRows.find((value) => driftScopeKey(value) === get().selectedScope)
    const value = row && parseDriftDraft(row.config_id, get().policyDraft)
    return value ? mutate(() => persistDistributionPolicy(value), true) : Promise.resolve(false)
  },
  chooseLiveBaseline: () => {
    const row = get().liveRows.find((value) => driftScopeKey(value) === get().selectedScope)
    return row?.current_report_id ? mutate(() => chooseDistributionBaseline(row.current_report_id!)) : Promise.resolve(false)
  },
  ackLiveAlert: (alertId) => mutate(() => acknowledgeDistributionAlert(alertId)),
}))
