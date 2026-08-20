import { create } from 'zustand'
import { DRIFT_ALERT, DRIFT_WARN } from '@/constants/simulation'

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
}

export const useMonitoringStore = create<MonitoringStore>((set) => ({
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
}))
