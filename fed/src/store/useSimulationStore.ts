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
  NodeState,
  NodeStatus,
  PacketDirection,
  SimulationConfig,
  TabId,
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

  // Logs
  logs: LogEntry[]
  logFilter: LogFilter

  // UI
  activeTab: TabId

  // Actions: config
  setAlgorithm: (algorithm: Algorithm) => void
  setTotalRounds: (rounds: number) => void
  setLocalEpochs: (epochs: number) => void
  setLearningRate: (lr: number) => void

  // Actions: navigation
  setActiveTab: (tab: TabId) => void
  setLogFilter: (filter: LogFilter) => void

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
  setGlobal: (partial: Partial<GlobalMetrics>) => void
  addChartPoint: (point: ChartPoint) => void

  // Actions: logs
  log: (kind: LogKind, message: string, nodeId?: number) => void
  clearLogs: () => void
}

let logSeq = 1
const nextLogId = (): number => logSeq++

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

  logs: [SYSTEM_INIT_LOG],
  logFilter: 'all',

  activeTab: 'dashboard',

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
    }),

  incrementRound: () => set((state) => ({ currentRound: state.currentRound + 1 })),

  setAllNodeStatus: (status) =>
    set((state) => ({
      nodes: state.nodes.map((n) => ({ ...n, status })),
    })),

  setAllNodeCpu: ([min, max]) =>
    set((state) => ({
      nodes: state.nodes.map((n) => ({
        ...n,
        cpu: Math.floor(Math.random() * (max - min + 1)) + min,
      })),
    })),

  updateNodeMetrics: (id, partial) =>
    set((state) => ({
      nodes: state.nodes.map((n) => (n.id === id ? { ...n, ...partial } : n)),
    })),

  setPacketDirection: (packetDirection) => set({ packetDirection }),

  setGlobal: (partial) =>
    set((state) => ({ global: { ...state.global, ...partial } })),

  addChartPoint: (point) =>
    set((state) => ({ chartPoints: [...state.chartPoints, point] })),

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
