import type { Algorithm, TabId } from '@/types/simulation'

export const NODE_COUNT = 12 as const

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
} as const

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

export const TAB_META: Record<TabId, { title: string; desc: string; icon: string }> = {
  dashboard: {
    title: '메인 대시보드',
    desc: '연합컴퓨팅 시스템의 토폴로지와 학습 사이클을 시뮬레이션하고 통제합니다.',
    icon: 'fa-chart-pie',
  },
  nodes: {
    title: '분산 노드 관리',
    desc: '각 개별 원격 연계 클라이언트의 로컬 프라이버시 데이터셋 크기, 하드웨어 부하 지표 및 성능을 감시합니다.',
    icon: 'fa-server',
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
