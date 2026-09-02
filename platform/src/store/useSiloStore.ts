import { create } from 'zustand'
import { SILO_SEEDS } from '@/constants/simulation'
import { createNode } from '@/lib/nodeFactory'
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

export interface NewSiloInput {
  name: string
  endpoint: string
  collectIntervalSec: number
  /** 하위 노드를 매달 상위 사일로 id (1~12). 계층 깊이는 2단으로 제한된다 */
  parentId: number
}

export interface SiloStore {
  silos: Silo[]
  addSilo: (input: NewSiloInput) => void
  updateThreshold: (id: number, partial: Partial<SiloThresholds>) => void
  removeSilo: (id: number) => void
  /** 목 off — 사일로 목록을 비운다 */
  clearAll: () => void
  /** 목 on — 초기 시드로 복원한다 */
  reseed: () => void
  /** 라이브 모드 — 서버 폴링 결과로 목록을 통째로 교체한다 */
  setSilos: (silos: Silo[]) => void
}

export const useSiloStore = create<SiloStore>((set, get) => ({
  silos: seedSilos(),

  clearAll: () => set({ silos: [] }),
  reseed: () => set({ silos: seedSilos() }),
  setSilos: (silos) => set({ silos }),

  addSilo: (input) => {
    const parent = get().silos.find((s) => s.id === input.parentId)
    if (!parent) {
      logToConsole('error', '상위 사일로를 찾을 수 없어 하위 노드 등록을 취소했습니다.')
      return
    }
    // 계층 깊이 2단 제한 — 하위 노드 밑에 다시 하위를 매달 수 없다
    if (parent.parentId !== undefined) {
      logToConsole('error', `[${parent.name}]은(는) 하위 노드이므로 그 아래에 다시 증설할 수 없습니다.`)
      return
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
    // 1단 사일로는 연합 구조의 고정 참여자 — 하위 노드만 해제할 수 있다
    if (target.parentId === undefined) {
      logToConsole('error', `[${target.name}]은(는) 1단 사일로이므로 해제할 수 없습니다.`)
      return
    }
    set((state) => ({ silos: state.silos.filter((s) => s.id !== id) }))
    useDataStore.getState().removeSiloData(id)
    useSimulationStore.getState().removeNode(id)
    logToConsole('error', `[${target.name}] 하위 노드 등록을 해제했습니다.`)
  },
}))
