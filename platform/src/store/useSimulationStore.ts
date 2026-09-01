import { create } from 'zustand'
import { DEFAULT_CONFIG, INITIAL_GLOBAL } from '@/constants/simulation'
import { effectiveEnabledNodes } from '@/lib/aggregation'
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
  /**
   * 목 데이터 시뮬레이션 on/off.
   * false면 하트비트 로그·학습 시작이 멈춘다 — 실서버 연동 어댑터가 붙을 자리.
   */
  mockEnabled: boolean

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

  // Actions: data source
  setMockEnabled: (enabled: boolean) => void
  /** 목 off — 시뮬레이션 데이터를 전부 비운다 (실서버 연동 대기 상태) */
  clearMockData: () => void
  /** 라이브 모드 — 서버 폴링 결과를 반영한다 (부분 갱신) */
  applyLiveSnapshot: (
    partial: Partial<
      Pick<SimulationStore, 'chartPoints' | 'monitorPoints' | 'currentRound' | 'global'>
    >,
  ) => void

  // Actions: engine lifecycle
  startRunning: () => void
  pauseRunning: () => void
  reset: () => void

  // Actions: per-round
  incrementRound: () => void
  setAllNodeStatus: (status: NodeStatus) => void
  setAllNodeCpu: (range: [min: number, max: number]) => void
  /** HFL 엣지 단계에서 하위/상위 노드에 서로 다른 상태를 부여할 때 사용 */
  setNodeStatusByIds: (ids: readonly number[], status: NodeStatus) => void
  updateNodeMetrics: (id: number, partial: Partial<Pick<NodeState, 'acc' | 'loss'>>) => void
  setPacketDirection: (direction: PacketDirection) => void

  // Actions: node control
  toggleNode: (id: number) => void
  restartNode: (id: number) => void
  /** 하위 노드 등록 — useSiloStore에서 전파된다 */
  addNode: (node: NodeState) => void
  /** 하위 노드 해제 — useSiloStore에서 전파된다 */
  removeNode: (id: number) => void
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

// --- 목 데이터 스위치 영속화 -------------------------------------------------
const MOCK_STORAGE_KEY = 'fed-mock-enabled'

/** 저장된 값이 없으면 꺼짐 — 기본은 실데이터(라이브) 모드, 데모는 설정에서 켠다. */
function readInitialMockEnabled(): boolean {
  try {
    return window.localStorage.getItem(MOCK_STORAGE_KEY) === 'true'
  } catch {
    return false
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

export const useSimulationStore = create<SimulationStore>((set, get) => ({
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
  mockEnabled: readInitialMockEnabled(),

  setMockEnabled: (enabled) => {
    try {
      window.localStorage.setItem(MOCK_STORAGE_KEY, String(enabled))
    } catch {
      // 저장 실패는 무시 — 세션 내 전환은 정상 동작
    }
    set({ mockEnabled: enabled })
    get().log(
      'system',
      enabled
        ? '목 데이터 시뮬레이션 활성화 — 데모 모드로 동작합니다.'
        : '목 데이터 시뮬레이션 비활성화 — 실서버 연동 대기 모드입니다.',
    )
  },

  clearMockData: () =>
    set({
      isRunning: false,
      isPaused: false,
      currentRound: 0,
      nodes: [],
      global: { accuracy: 0, loss: 0, accumulatedTraffic: 0 },
      packetDirection: 'idle',
      chartPoints: [],
      monitorPoints: [],
      // 하트비트·라운드 로그도 목 산출물이므로 함께 비운다
      logs: [],
    }),

  applyLiveSnapshot: (partial) => set(partial),

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
    set((state) => ({
      isRunning: false,
      isPaused: false,
      currentRound: 0,
      // 등록된 하위 노드는 보존하고 학습 지표만 초기화한다.
      // (nodeFactory가 useSiloStore를 읽으면 순환 import가 되므로 자기 state에서 걸러낸다)
      nodes: [
        ...createInitialNodes(),
        ...state.nodes
          .filter((n) => n.parentId !== undefined)
          .map((n) => ({
            ...n,
            acc: 0,
            loss: 0,
            cpu: 0,
            status: 'idle' as const,
            pending: false,
          })),
      ],
      global: { ...INITIAL_GLOBAL },
      packetDirection: 'idle',
      chartPoints: [initialChartPoint()],
      monitorPoints: [],
    })),

  incrementRound: () =>
    set((state) => ({
      currentRound: state.currentRound + 1,
      // 지난 라운드 도중 증설된 노드를 이번 라운드부터 참여시킨다.
      // 대기 노드가 없으면 배열 참조를 유지해 불필요한 리렌더를 막는다.
      nodes: state.nodes.some((n) => n.pending)
        ? state.nodes.map((n) => (n.pending ? { ...n, pending: false } : n))
        : state.nodes,
    })),

  setAllNodeStatus: (status) =>
    set((state) => {
      // 비활성 노드(및 상위가 끊긴 하위 노드)는 라운드에 참여하지 않으므로 idle 유지
      const activeIds = new Set(effectiveEnabledNodes(state.nodes).map((n) => n.id))
      return {
        nodes: state.nodes.map((n) => (activeIds.has(n.id) ? { ...n, status } : n)),
      }
    }),

  setAllNodeCpu: ([min, max]) =>
    set((state) => {
      const activeIds = new Set(effectiveEnabledNodes(state.nodes).map((n) => n.id))
      return {
        nodes: state.nodes.map((n) =>
          activeIds.has(n.id)
            ? { ...n, cpu: Math.floor(Math.random() * (max - min + 1)) + min }
            : n,
        ),
      }
    }),

  setNodeStatusByIds: (ids, status) =>
    set((state) => {
      const target = new Set(ids)
      return {
        nodes: state.nodes.map((n) => (target.has(n.id) ? { ...n, status } : n)),
      }
    }),

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

  addNode: (node) =>
    set((state) => ({
      // 라운드가 도는 중에 들어온 노드는 학습 이력이 없으므로 다음 라운드까지 대기시킨다
      nodes: [...state.nodes, state.isRunning ? { ...node, pending: true } : node],
    })),

  removeNode: (id) =>
    set((state) => ({ nodes: state.nodes.filter((n) => n.id !== id) })),

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

// 초기 테마를 DOM에 반영 — index.html 인라인 스크립트가 없거나
// 빌드 과정에서 제거된 경우에도 첫 렌더가 올바른 테마로 그려지도록 보장한다.
applyTheme(useSimulationStore.getState().theme)
