import { create } from 'zustand'
import { DEFAULT_CONFIG, INITIAL_GLOBAL, NODE_COUNT } from '@/constants/simulation'
import { createInitialNodes } from '@/lib/nodeFactory'
import { nowTimestamp } from '@/lib/format'
import type {
  Algorithm,
  ChartPoint,
  GlobalMetrics,
  LogEntry,
  LogFilter,
  LogKind,
  MonitorPoint,
  NodeState,
  NodeStatus,
  PacketDirection,
  SimulationConfig,
  TabId,
  ThemeMode,
} from '@/types/simulation'

export interface SimulationStore {
  // Configuration (user-controlled)
  config: SimulationConfig

  // Engine state
  isRunning: boolean
  isPaused: boolean
  currentRound: number

  // Nodes & global metrics
  nodes: NodeState[]
  global: GlobalMetrics

  // Topology/animation state
  packetDirection: PacketDirection

  // Chart history
  chartPoints: ChartPoint[]
  // 모델 모니터링 지표 시계열 (처리량/처리시간/드리프트)
  monitorPoints: MonitorPoint[]

  // Logs
  logs: LogEntry[]
  logFilter: LogFilter

  // UI
  activeTab: TabId
  theme: ThemeMode

  // Actions: config
  setAlgorithm: (algorithm: Algorithm) => void
  setTotalRounds: (rounds: number) => void
  setLocalEpochs: (epochs: number) => void
  setLearningRate: (lr: number) => void

  // Actions: navigation
  setActiveTab: (tab: TabId) => void
  setLogFilter: (filter: LogFilter) => void

  // Actions: theme
  setTheme: (theme: ThemeMode) => void
  toggleTheme: () => void

  // Actions: engine lifecycle
  startRunning: () => void
  pauseRunning: () => void
  reset: () => void

  // Actions: per-round
  incrementRound: () => void
  setAllNodeStatus: (status: NodeStatus) => void
  setAllNodeCpu: (range: [min: number, max: number]) => void
  updateNodeMetrics: (id: number, partial: Partial<Pick<NodeState, 'acc' | 'loss'>>) => void
  setPacketDirection: (direction: PacketDirection) => void

  // Actions: node control
  toggleNode: (id: number) => void
  restartNode: (id: number) => void
  setGlobal: (partial: Partial<GlobalMetrics>) => void
  addChartPoint: (point: ChartPoint) => void
  addMonitorPoint: (point: MonitorPoint) => void

  // Actions: logs
  log: (kind: LogKind, message: string, nodeId?: number) => void
  clearLogs: () => void
}

let logSeq = 1
const nextLogId = (): number => logSeq++

// --- 테마 영속화 + DOM 반영 -------------------------------------------------
const THEME_STORAGE_KEY = 'fed-theme'

/** localStorage → 시스템 선호도 순으로 초기 테마를 결정한다. */
function readInitialTheme(): ThemeMode {
  if (typeof window === 'undefined') return 'dark'
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    // localStorage 접근 불가(프라이빗 모드 등) — 시스템 선호도로 폴백
  }
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

/** `<html data-theme>` 속성과 localStorage를 동기화한다. */
function applyTheme(theme: ThemeMode): void {
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', theme)
  }
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // 저장 실패는 무시 — 세션 내 전환은 정상 동작
  }
}

const SYSTEM_INIT_LOG: LogEntry = {
  id: nextLogId(),
  time: nowTimestamp(),
  kind: 'system',
  message: '연합컴퓨팅 오케스트레이터 인터페이스 초기화 완료. 새로운 학습 구성 대기 중...',
}

function initialChartPoint(): ChartPoint {
  return { round: 0, accuracy: INITIAL_GLOBAL.accuracy, loss: INITIAL_GLOBAL.loss }
}

export const useSimulationStore = create<SimulationStore>((set) => ({
  config: { ...DEFAULT_CONFIG },

  isRunning: false,
  isPaused: false,
  currentRound: 0,

  nodes: createInitialNodes(),
  global: { ...INITIAL_GLOBAL },

  packetDirection: 'idle',

  chartPoints: [initialChartPoint()],
  monitorPoints: [],

  logs: [SYSTEM_INIT_LOG],
  logFilter: 'all',

  activeTab: 'dashboard',
  theme: readInitialTheme(),

  setAlgorithm: (algorithm) =>
    set((state) => ({ config: { ...state.config, algorithm } })),
  setTotalRounds: (totalRounds) =>
    set((state) => ({ config: { ...state.config, totalRounds } })),
  setLocalEpochs: (localEpochs) =>
    set((state) => ({ config: { ...state.config, localEpochs } })),
  setLearningRate: (learningRate) =>
    set((state) => ({ config: { ...state.config, learningRate } })),

  setActiveTab: (activeTab) => set({ activeTab }),
  setLogFilter: (logFilter) => set({ logFilter }),

  setTheme: (theme) => {
    applyTheme(theme)
    set({ theme })
  },
  toggleTheme: () =>
    set((state) => {
      const theme: ThemeMode = state.theme === 'dark' ? 'light' : 'dark'
      applyTheme(theme)
      return { theme }
    }),

  startRunning: () => set({ isRunning: true, isPaused: false }),
  pauseRunning: () => set({ isPaused: true }),

  reset: () =>
    set({
      isRunning: false,
      isPaused: false,
      currentRound: 0,
      nodes: createInitialNodes(),
      global: { ...INITIAL_GLOBAL },
      packetDirection: 'idle',
      chartPoints: [initialChartPoint()],
      monitorPoints: [],
    }),

  incrementRound: () => set((state) => ({ currentRound: state.currentRound + 1 })),

  setAllNodeStatus: (status) =>
    set((state) => ({
      // 비활성 노드는 라운드에 참여하지 않으므로 idle 유지
      nodes: state.nodes.map((n) => (n.enabled ? { ...n, status } : n)),
    })),

  setAllNodeCpu: ([min, max]) =>
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.enabled ? { ...n, cpu: Math.floor(Math.random() * (max - min + 1)) + min } : n,
      ),
    })),

  updateNodeMetrics: (id, partial) =>
    set((state) => ({
      nodes: state.nodes.map((n) => (n.id === id ? { ...n, ...partial } : n)),
    })),

  setPacketDirection: (packetDirection) => set({ packetDirection }),

  toggleNode: (id) =>
    set((state) => ({
      nodes: state.nodes.map((n) => {
        if (n.id !== id) return n
        const enabled = !n.enabled
        return enabled ? { ...n, enabled } : { ...n, enabled, status: 'idle', cpu: 0 }
      }),
    })),

  restartNode: (id) =>
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === id ? { ...n, status: 'idle', cpu: 0, acc: 0, loss: 0 } : n,
      ),
    })),

  setGlobal: (partial) =>
    set((state) => ({ global: { ...state.global, ...partial } })),

  addChartPoint: (point) =>
    set((state) => ({ chartPoints: [...state.chartPoints, point] })),

  addMonitorPoint: (point) =>
    set((state) => ({ monitorPoints: [...state.monitorPoints, point] })),

  log: (kind, message, nodeId) =>
    set((state) => ({
      logs: [
        ...state.logs,
        {
          id: nextLogId(),
          time: nowTimestamp(),
          kind,
          message,
          ...(nodeId !== undefined ? { nodeId } : {}),
        },
      ],
    })),

  clearLogs: () =>
    set({
      logs: [
        {
          id: nextLogId(),
          time: nowTimestamp(),
          kind: 'system',
          message: '오케스트레이터 로그 콘솔이 비워졌습니다.',
        },
      ],
    }),
}))

export const NODE_COUNT_REF = NODE_COUNT

// 초기 테마를 DOM에 반영 — index.html 인라인 스크립트가 없거나
// 빌드 과정에서 제거된 경우에도 첫 렌더가 올바른 테마로 그려지도록 보장한다.
applyTheme(useSimulationStore.getState().theme)
