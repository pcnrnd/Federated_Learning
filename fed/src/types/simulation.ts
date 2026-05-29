export type Algorithm = 'fedavg' | 'fedmedian' | 'secagg'

export type NodeStatus = 'idle' | 'syncing' | 'training' | 'uploading'

export type LogKind = 'system' | 'server' | 'client' | 'success' | 'error'

export type PacketDirection = 'idle' | 'download' | 'upload' | 'local'

export type TabId = 'dashboard' | 'nodes' | 'analytics' | 'logs'

export type LogFilter = 'all' | 'system' | 'server' | 'nodes'

export interface NodeState {
  id: number
  name: string
  size: number
  delay: number
  mult: number
  acc: number
  loss: number
  cpu: number
  status: NodeStatus
  normalPct: number
  abnormalPct: number
}

export interface SimulationConfig {
  algorithm: Algorithm
  totalRounds: number
  localEpochs: number
  learningRate: number
}

export interface GlobalMetrics {
  accuracy: number
  loss: number
  accumulatedTraffic: number
}

export interface ChartPoint {
  round: number
  accuracy: number
  loss: number
}

export interface LogEntry {
  id: number
  time: string
  kind: LogKind
  nodeId?: number
  message: string
}
