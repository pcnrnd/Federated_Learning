export type Algorithm = 'fedavg' | 'fedmedian' | 'secagg'

export type NodeStatus = 'idle' | 'syncing' | 'training' | 'uploading'

export type LogKind = 'system' | 'server' | 'client' | 'success' | 'error'

export type PacketDirection = 'idle' | 'download' | 'upload' | 'local'

export type TabId =
  | 'dashboard'
  | 'nodes'
  | 'silos'
  | 'data'
  | 'models'
  | 'analytics'
  | 'logs'

export type ModelStatus = 'deployed' | 'experimental' | 'archived'

export type LogFilter = 'all' | 'system' | 'server' | 'nodes'

/** UI 색상 테마. `<html data-theme>`로 반영된다. */
export type ThemeMode = 'dark' | 'light'

/**
 * 사일로의 학습 런타임 상태.
 * 엔진(`useSimulationStore.nodes`)이 다루는 학습 참여자이며,
 * `id`는 `useSiloStore`(리소스)·`useDataStore`(파이프라인)의 사일로와 동일 식별자다.
 */
export interface NodeState {
  id: number
  /** 사일로 전체 명칭 (SILO_SEEDS.name) */
  name: string
  /** 토폴로지용 축약 명칭 (SILO_SEEDS.shortName) */
  shortName: string
  size: number
  delay: number
  mult: number
  acc: number
  loss: number
  cpu: number
  status: NodeStatus
  normalPct: number
  abnormalPct: number
  /** 라운드 참여 여부. false면 학습/집계에서 제외 */
  enabled: boolean
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

export interface ModelVersion {
  id: string
  project: string
  version: string
  status: ModelStatus
  accuracy: number
  algorithm: Algorithm
  rounds: number
  createdAt: string
  note?: string
}

/** 모델 패키징(컨테이너화) 진행 상태 */
export type PackageState = 'idle' | 'building' | 'built'

/** 배포 전략: 일괄 / 실시간 / 에지 */
export type DeployStrategy = 'batch' | 'realtime' | 'edge'

/** 배포 라이프사이클 상태 */
export type DeployState = 'pending' | 'deploying' | 'done' | 'failed'

export interface ModelPackage {
  modelId: string
  state: PackageState
  runtime: string
  imageTag: string
  builtAt?: string
}

export interface Deployment {
  id: string
  modelId: string
  /** 표시용 모델 라벨(프로젝트 + 버전) 스냅샷 */
  modelLabel: string
  strategy: DeployStrategy
  /** 배포 대상 사일로 id 목록. 선택 배포(edge)에서만 채워지고, 그 외 전략은 전체 사일로 대상이라 빈 배열 */
  targetSiloIds: number[]
  /** 일괄 배포 주기(초). batch 전략에서만 사용 */
  intervalSec?: number
  state: DeployState
  ts: string
}

// --- 6.6 사일로 리소스 모니터링 + 등록 ---

export interface SiloThresholds {
  cpu: number
  mem: number
  disk: number
}

export interface Silo {
  id: number
  name: string
  endpoint: string
  collectIntervalSec: number
  cpu: number
  mem: number
  disk: number
  thresholds: SiloThresholds
}

// --- 6.4 사일로 데이터 정제 · 샤딩 ---

export interface SiloData {
  siloId: number
  name: string
  /** 정제 완료율(%) */
  cleansePct: number
  /** 분산 샤드 수 */
  shardCount: number
  /** 원본 레코드 수 */
  records: number
}

// --- 6.5 배치 스케줄러 · 데이터 파이프라인 ---

export type JobState = 'queued' | 'running' | 'done' | 'failed'

export interface Job {
  id: string
  name: string
  /** cron 또는 주기 표현 문자열 */
  schedule: string
  /** 선행 의존 작업 id 목록 */
  dependsOn: string[]
  state: JobState
  /** 대상 사일로 id. undefined면 전체 사일로 공통 단계 */
  targetSiloId?: number
}

// --- 6.3 모델 모니터링 (Analytics 확장) ---

export interface MonitorPoint {
  round: number
  /** 처리량 (req/s) */
  throughput: number
  /** 처리시간 (ms) */
  latency: number
  /** 데이터 드리프트 점수 (0~1) */
  drift: number
}
