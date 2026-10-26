import { isLiveConfigured } from '@/api/client'

export type UiDataMode = 'demo' | 'live' | 'unconfigured'

export function resolveUiDataMode(mockEnabled: boolean): UiDataMode {
  if (mockEnabled) return 'demo'
  return isLiveConfigured() ? 'live' : 'unconfigured'
}

export const LIVE_SIMULATION_RESET_REASON =
  '로컬 시뮬레이터 초기화만 지원합니다. 실제 학습 작업 취소는 데이터 탭에서 수행하세요.'

export const LIVE_ALGORITHM_REASON = '실제 ridge 연합 학습은 서버 solver(ridge_gradient_v1)로 고정됩니다.'

export const LIVE_METRIC_FIELD_REASON = '실서버 등록에는 정확도·라운드 수를 입력하지 않습니다.'

export const LIVE_CRON_FIELD_REASON =
  '실서버 정제·학습 스케줄은 고급 설정의 scheduled_at·interval_seconds를 사용합니다.'

export const LIVE_DEMO_CAPABILITY_REASON = '실서버 데이터 조회 상태에서 설정할 수 있습니다.'

export const LIVE_NODE_TOGGLE_REASON = '등록 사일로 참여는 서버 그룹·학습 작업 설정으로 관리됩니다.'

export const LIVE_NODE_RESTART_REASON = '사일로 프로세스 재시작은 이 화면에서 지원하지 않습니다.'

export const UNCONFIGURED_API_MESSAGE =
  '실데이터 API 주소 설정이 필요합니다. 환경 변수 VITE_API_BASE를 설정한 뒤 다시 시도하세요.'

export const LIVE_JOB_SELECT_REASON = '일시정지·재개·취소할 실제 학습 작업을 먼저 선택하세요.'

export const LIVE_TRAINING_JOB_CAPABILITY_REASON =
  '실제 학습 작업 선택·취소는 실서버 데이터 조회 상태에서 사용할 수 있습니다.'

export const LIVE_TERMINAL_JOB_REASON =
  '종료된 작업(completed/failed/cancelled)에는 일시정지·재개·취소·새 시작을 적용할 수 없습니다. 선택을 해제한 뒤 새 작업을 등록하세요.'
