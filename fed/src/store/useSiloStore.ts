import { create } from 'zustand'
import { SILO_SEEDS } from '@/constants/simulation'
import { useDataStore } from '@/store/useDataStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { LogKind, Silo, SiloThresholds } from '@/types/simulation'

// 시드(SILO_SEEDS) 다음 id부터 신규 등록 사일로에 부여
let siloSeq = SILO_SEEDS.length + 1
const nextSiloId = (): number => siloSeq++

function logToConsole(kind: LogKind, message: string): void {
  useSimulationStore.getState().log(kind, message)
}

const DEFAULT_THRESHOLDS: SiloThresholds = { cpu: 85, mem: 80, disk: 90 }

/** 12개 사일로의 리소스 관점 시드 — 학습/파이프라인과 동일한 id·이름 공유 */
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

export interface NewSiloInput {
  name: string
  endpoint: string
  collectIntervalSec: number
}

export interface SiloStore {
  silos: Silo[]
  addSilo: (input: NewSiloInput) => void
  updateThreshold: (id: number, partial: Partial<SiloThresholds>) => void
  removeSilo: (id: number) => void
}

export const useSiloStore = create<SiloStore>((set, get) => ({
  silos: seedSilos(),

  addSilo: (input) => {
    const silo: Silo = {
      id: nextSiloId(),
      name: input.name.trim(),
      endpoint: input.endpoint.trim(),
      collectIntervalSec: input.collectIntervalSec,
      // 신규 등록 사일로는 초기 수집 전이므로 0에서 시작
      cpu: 0,
      mem: 0,
      disk: 0,
      thresholds: { ...DEFAULT_THRESHOLDS },
    }
    set((state) => ({ silos: [...state.silos, silo] }))
    // 데이터 파이프라인 탭에도 신규 사일로가 나타나도록 전파
    useDataStore.getState().ensureSiloData(silo.id)
    logToConsole('server', `[${silo.name}] 사일로를 등록했습니다. (${silo.endpoint}, 수집주기 ${silo.collectIntervalSec}s)`)
  },

  updateThreshold: (id, partial) => {
    const target = get().silos.find((s) => s.id === id)
    if (!target) return
    set((state) => ({
      silos: state.silos.map((s) =>
        s.id === id ? { ...s, thresholds: { ...s.thresholds, ...partial } } : s,
      ),
    }))
    logToConsole('system', `[${target.name}] 리소스 임계값을 갱신했습니다.`)
  },

  removeSilo: (id) => {
    const target = get().silos.find((s) => s.id === id)
    if (!target) return
    set((state) => ({ silos: state.silos.filter((s) => s.id !== id) }))
    useDataStore.getState().removeSiloData(id)
    logToConsole('error', `[${target.name}] 사일로 등록을 해제했습니다.`)
  },
}))
