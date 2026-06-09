import type { Algorithm, DeployStrategy, TabId } from '@/types/simulation'

/**
 * 연합학습 참여 사일로의 단일 정의 소스(SSOT).
 * 같은 12개 사일로를 세 관점으로 본다:
 *  - 학습 런타임(엔진 nodes, `nodeFactory`)
 *  - 리소스/등록(`useSiloStore`)
 *  - 데이터 파이프라인(`useDataStore`)
 * id는 세 store에서 공통 식별자로 사용된다.
 */
export interface SiloSeed {
  id: number
  /** 카드·목록용 전체 명칭 */
  name: string
  /** 토폴로지 등 좁은 영역용 축약 명칭 */
  shortName: string
  /** 사일로 수집 엔드포인트(base_url) */
  endpoint: string
  /** 파라미터/지표 수집 주기(초) */
  collectIntervalSec: number
  /** 리소스 모니터링 기준치(%) */
  cpu: number
  mem: number
  disk: number
}

// PoC 단계: 사일로는 도메인명 없이 번호로만 식별 (사일로1 ~ 사일로12)
export const SILO_SEEDS: readonly SiloSeed[] = [
  { id: 1, name: '사일로1', shortName: '사일로1', endpoint: 'tcp://10.0.0.11:2375', collectIntervalSec: 15, cpu: 62, mem: 71, disk: 48 },
  { id: 2, name: '사일로2', shortName: '사일로2', endpoint: 'tcp://10.0.0.12:2375', collectIntervalSec: 15, cpu: 54, mem: 60, disk: 52 },
  { id: 3, name: '사일로3', shortName: '사일로3', endpoint: 'tcp://10.0.0.13:2375', collectIntervalSec: 30, cpu: 88, mem: 64, disk: 55 },
  { id: 4, name: '사일로4', shortName: '사일로4', endpoint: 'tcp://10.0.0.14:2375', collectIntervalSec: 30, cpu: 47, mem: 58, disk: 61 },
  { id: 5, name: '사일로5', shortName: '사일로5', endpoint: 'tcp://10.0.0.15:2375', collectIntervalSec: 30, cpu: 39, mem: 49, disk: 44 },
  { id: 6, name: '사일로6', shortName: '사일로6', endpoint: 'tcp://10.0.0.16:2375', collectIntervalSec: 20, cpu: 73, mem: 66, disk: 70 },
  { id: 7, name: '사일로7', shortName: '사일로7', endpoint: 'tcp://10.0.0.17:2375', collectIntervalSec: 20, cpu: 58, mem: 52, disk: 63 },
  { id: 8, name: '사일로8', shortName: '사일로8', endpoint: 'tcp://10.0.0.18:2375', collectIntervalSec: 25, cpu: 66, mem: 78, disk: 57 },
  { id: 9, name: '사일로9', shortName: '사일로9', endpoint: 'tcp://10.0.0.19:2375', collectIntervalSec: 60, cpu: 33, mem: 41, disk: 38 },
  { id: 10, name: '사일로10', shortName: '사일로10', endpoint: 'tcp://10.0.0.20:2375', collectIntervalSec: 25, cpu: 71, mem: 69, disk: 74 },
  { id: 11, name: '사일로11', shortName: '사일로11', endpoint: 'tcp://10.0.0.21:2375', collectIntervalSec: 10, cpu: 41, mem: 83, disk: 92 },
  { id: 12, name: '사일로12', shortName: '사일로12', endpoint: 'tcp://10.0.0.22:2375', collectIntervalSec: 10, cpu: 49, mem: 80, disk: 88 },
] as const

/** 연합학습 참여 사일로 수 (= 학습 노드 수). SILO_SEEDS 길이로 단일화. */
export const NODE_COUNT = SILO_SEEDS.length

export const TOPOLOGY = {
  centerX: 250,
  centerY: 180,
  radius: 135,
  viewBox: { width: 500, height: 360 },
} as const

export const INITIAL_GLOBAL = {
  accuracy: 28.5,
  loss: 2.15,
  accumulatedTraffic: 0,
} as const

export const DEFAULT_CONFIG = {
  algorithm: 'fedavg' as Algorithm,
  totalRounds: 15,
  localEpochs: 5,
  learningRate: 0.01,
}

export const CONFIG_BOUNDS = {
  rounds: { min: 5, max: 50 },
  epochs: { min: 1, max: 10 },
  learningRate: { min: 0.001, max: 0.1, step: 0.001 },
} as const

export const TRAFFIC_PER_NODE_MB = {
  fedavg: 1.15,
  fedmedian: 1.15,
  secagg: 2.25,
} as const satisfies Record<Algorithm, number>

export const TIMINGS = {
  downloadAnimationMs: 1600,
  syncDelayMs: 800,
  trainingTotalMs: 2200,
  uploadDelayMs: 800,
  aggregationMs: 1200,
  betweenRoundsMs: 2000,
  /** Idle 상태 시스템 하트비트 로그 주기 */
  heartbeatIntervalMs: 4500,
} as const

/** 차트 초기 상태(단일 포인트)에서 추이 미리보기용 시드 데이터 */
export const CHART_PREVIEW_POINTS = [
  { round: 0, accuracy: 28.5, loss: 2.15 },
  { round: 3, accuracy: 44.2, loss: 1.72 },
  { round: 6, accuracy: 61.8, loss: 1.18 },
  { round: 9, accuracy: 77.5, loss: 0.62 },
  { round: 12, accuracy: 88.3, loss: 0.24 },
] as const

export const ALGORITHM_LABEL: Record<Algorithm, string> = {
  fedavg: 'FedAvg (연합 가중 평균)',
  fedmedian: 'Federated Median (이상치 견고)',
  secagg: 'Secure Aggregation (암호 보안 합산)',
}

export const ALGORITHM_OPTIONS: Array<{ value: Algorithm; label: string }> = [
  { value: 'fedavg', label: 'FedAvg (연합 가중 평균)' },
  { value: 'fedmedian', label: 'Federated Median (이상치 내성)' },
  { value: 'secagg', label: 'Secure Aggregation (보안 합산)' },
]

/** 모델 패키징/배포 목 진행 타이밍 */
export const DEPLOY_TIMINGS = {
  packageBuildMs: 1400,
  /** pending→deploying, deploying→done 각 단계 간격 */
  deployStepMs: 1300,
} as const

/** 패키징 컨테이너 런타임 선택지(목) */
export const RUNTIME_OPTIONS: ReadonlyArray<string> = [
  'python:3.11-slim',
  'python:3.12-slim',
  'pytorch/pytorch:2.3.0-cuda12.1',
]

/** 배포 전략 메타: 라디오/세그먼트 렌더용 */
export const DEPLOY_STRATEGY_META: Record<
  DeployStrategy,
  { label: string; desc: string; icon: string }
> = {
  batch: {
    label: '일괄 배포',
    desc: '지정한 주기로 모델을 일괄 배포합니다.',
    icon: 'fa-layer-group',
  },
  realtime: {
    label: '실시간 배포',
    desc: '즉시 전체 사일로에 모델을 배포합니다.',
    icon: 'fa-bolt',
  },
  edge: {
    label: '선택 배포',
    desc: '선택한 일부 사일로에만 모델을 배포합니다.',
    icon: 'fa-microchip',
  },
}

/** 데이터 처리 작업(배치 스케줄러) 목 진행 단계 간격 */
export const JOB_STEP_MS = 1600 as const

/** 데이터 드리프트 경고 임계치(0~1). 초과 시 시각 경보 */
export const DRIFT_WARN = 0.3 as const
export const DRIFT_ALERT = 0.5 as const

/** 모델 모니터링 차트 초기 미리보기 시드 */
export const MONITOR_PREVIEW_POINTS = [
  { round: 0, throughput: 120, latency: 88, drift: 0.08 },
  { round: 3, throughput: 168, latency: 76, drift: 0.12 },
  { round: 6, throughput: 205, latency: 64, drift: 0.19 },
  { round: 9, throughput: 242, latency: 57, drift: 0.27 },
  { round: 12, throughput: 268, latency: 51, drift: 0.34 },
] as const

export const TAB_META: Record<TabId, { title: string; desc: string; icon: string }> = {
  dashboard: {
    title: '메인 대시보드',
    desc: '연합컴퓨팅 시스템의 토폴로지와 학습 사이클을 시뮬레이션하고 통제합니다.',
    icon: 'fa-chart-pie',
  },
  nodes: {
    title: '사일로 학습 현황',
    desc: '연합학습에 참여하는 각 사일로의 로컬 프라이버시 데이터셋 크기, 하드웨어 부하 지표 및 학습 성능을 감시하고 참여 여부를 제어합니다.',
    icon: 'fa-server',
  },
  silos: {
    title: '사일로 리소스',
    desc: '각 사일로의 CPU·메모리·디스크 리소스를 취득·시각화하고 임계값을 사전 설정하며, 신규 사일로를 등록·연결합니다.',
    icon: 'fa-warehouse',
  },
  data: {
    title: '데이터 파이프라인',
    desc: '사일로 데이터의 정제 진행과 샤딩 분산 현황을 시각화하고, 배치 스케줄러로 데이터 처리 작업을 자동화합니다.',
    icon: 'fa-database',
  },
  models: {
    title: '모델 버전관리',
    desc: '프로젝트별 연합 학습 모델의 버전을 등록·추적하고, 배포·롤백·보관 등 모델 생애주기를 관리합니다.',
    icon: 'fa-cubes',
  },
  analytics: {
    title: '성능 분석 차트',
    desc: '다수의 학습 연합 라운드에 따른 손실값 감소 수렴 추이 및 글로벌 모델 정확도의 진화를 심도 있게 추적합니다.',
    icon: 'fa-chart-line',
  },
  logs: {
    title: '실시간 시스템 로그',
    desc: '중앙 오케스트레이터의 동적 지휘 및 전송 채널 패킷 통신 내역을 전수 모니터링합니다.',
    icon: 'fa-terminal',
  },
}
