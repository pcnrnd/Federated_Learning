export type Algorithm = 'fedavg' | 'fedmedian' | 'secagg'

export type NodeStatus = 'idle' | 'syncing' | 'training' | 'uploading' | 'aggregating'

export type LogKind = 'system' | 'server' | 'client' | 'success' | 'error'

export type PacketDirection =
  | 'idle'
  | 'download'
  | 'upload'
  | 'local'
  | 'edge-download'
  | 'edge-upload'

export type TabId =
  | 'dashboard'
  | 'nodes'
  | 'silos'
  | 'data'
  | 'models'
  | 'analytics'
  | 'visualization'
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
  /**
   * 상위 사일로 id. undefined면 중앙 서버에 직결된 1단 사일로다.
   * 값이 있으면 계층형 연합학습(HFL)의 하위 노드이며,
   * 상위 사일로가 로컬(엣지) 집계자 역할을 맡는다.
   */
  parentId?: number
  /**
   * 라운드 진행 중에 증설되어 아직 참여 대기 중인 노드.
   * 학습을 한 번도 못 한 채(acc=0) 집계에 끼면 그 라운드 글로벌 지표가 오염되므로
   * 다음 라운드 시작(`incrementRound`) 시점에 해제된다.
   */
  pending?: boolean
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
  artifactId?: string
  resultId?: string
  weightsChecksum?: string
}

export interface LiveModelDraft {
  mode: 'training' | 'artifact'
  round_id: string
  version: string
  name: string
  weights_path: string
}

/** 모델 패키징(컨테이너화) 진행 상태 */
export type PackageState = 'idle' | 'building' | 'built' | 'failed' | 'unknown'

/** 배포 전략: 일괄 / 실시간 / 에지 */
export type DeployStrategy = 'batch' | 'realtime' | 'edge'

/** 배포 라이프사이클 상태 (stopped/rolled_back은 실서버 배포 기록에서만 온다) */
export type DeployState = 'pending' | 'deploying' | 'done' | 'failed' | 'stopped' | 'rolled_back'

export interface ModelPackage {
  modelId: string
  state: PackageState
  runtime: string
  imageTag: string
  builtAt?: string
  imageDigest?: string
  artifactId?: string
  weightsChecksum?: string
  error?: string
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
  targetNodeIds?: string[]
  env?: Record<string, string>
  inferencePort?: number
  probeInputs?: unknown[]
  verifiedAt?: string
  imageId?: string
  targets?: Record<string, { status: 'pending' | 'launching' | 'running' | 'failed'; endpoint?: string | null;
    image_id?: string | null; weights_checksum?: string | null; error_code?: string | null }>
  isSchedule?: boolean
  scheduleActive?: boolean
  nextDueAt?: string
  occurrence?: number
  error?: string
  cleanupPending?: boolean
  previousDeploymentId?: string
}

// --- 6.6 사일로 리소스 모니터링 + 등록 ---

export interface SiloThresholds {
  cpu: number | null
  mem: number | null
  disk: number | null
}

export type ResourceHistoryMetric = keyof SiloThresholds | 'cpu_cores' | 'mem_used_bytes'

export interface Silo {
  id: number
  name: string
  endpoint: string
  collectIntervalSec: number
  cpu: number | null
  mem: number | null
  disk: number | null
  thresholds: SiloThresholds
  /** 상위 사일로 id. undefined면 1단 사일로. `NodeState.parentId`와 동일 의미 */
  parentId?: number
  serverId?: string
  parentServerId?: string
  lastSampleAt?: string
  sampleState?: 'fresh' | 'stale' | 'uncollected' | 'unsupported' | 'unverified'
  measurementScope?: Record<string, string>
  unavailable?: Record<string, string>
  cpuCores?: number | null
  memUsedBytes?: number | null
  capabilities?: Record<string, boolean>
  resourceGate?: 'unknown' | 'unmonitored' | 'available' | 'over_budget'
  gpuThreshold?: number | null
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
  /** 실서버 정제 샤드 상태. undefined면 목 시드 데이터 */
  cleanseStatus?: 'pending' | 'running' | 'retry_wait' | 'completed' | 'failed'
  /** 실서버 step별 정제 카운터 (해당 사일로 샤드분) */
  stepCounters?: Record<string, number>
}

// --- 정제 잡 현황 (실서버 연동 — /api/cleaning-jobs) ---

export type CleaningJobStatus = 'pending' | 'running' | 'completed' | 'partial' | 'failed'

export interface CleaningJobSummary {
  jobId: string
  /** 'name@version' 표시용 레시피 라벨 */
  recipe: string
  status: CleaningJobStatus
  datasetLabel: string
  totalRowsIn: number
  totalRowsOut: number
  /** step별 합산 카운터 (예: {drop_nulls: 20}) */
  counters: Record<string, number>
  updatedAt: string
  scheduledAt?: string | null
  intervalSeconds?: number | null
  dependsOn?: string[]
  occurrence?: number
  generation?: number
  progress?: number
  attempts?: string
  errors?: string[]
  events?: Array<{ event_id: string; message: string; at: string; kind: string }>
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
