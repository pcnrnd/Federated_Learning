import { isLiveConfigured } from '@/api/client'

export type UiDataMode = 'demo' | 'live' | 'unconfigured'

export function resolveUiDataMode(mockEnabled: boolean): UiDataMode {
  if (mockEnabled) return 'demo'
  return isLiveConfigured() ? 'live' : 'unconfigured'
}

export const LIVE_SIMULATION_RESET_REASON =
  '로컬 시뮬레이터 초기화만 지원합니다. 실제 학습 작업 취소는 데이터 탭에서 수행하세요.'

export const LIVE_NODE_TOGGLE_REASON = '등록 사일로 참여는 서버 그룹·학습 작업 설정으로 관리됩니다.'

export const LIVE_NODE_RESTART_REASON = '사일로 프로세스 재시작은 이 화면에서 지원하지 않습니다.'

export const DEMO_RETRAINING_REASON = '실제 재교육 API는 데모 데이터가 꺼진 상태에서만 사용할 수 있습니다.'

export const UNCONFIGURED_API_MESSAGE =
  '실데이터 API 주소 설정이 필요합니다. 환경 변수 VITE_API_BASE를 설정한 뒤 다시 시도하세요.'
