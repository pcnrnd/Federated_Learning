import { isLiveConfigured } from '@/api/client'
import { useSimulationStore } from '@/store/useSimulationStore'

export function DataSourceStatus() {
  const demo = useSimulationStore((s) => s.mockEnabled)
  const status = useSimulationStore((s) => s.liveStatus)
  const error = useSimulationStore((s) => s.liveError)
  // 정상 상태는 두 모드 모두 안내 줄 없이 같은 레이아웃을 쓴다. 조치가 필요한 상태만 표시한다.
  if (demo || (isLiveConfigured() && status === 'ready')) return null
  const label = !isLiveConfigured() ? '실데이터 API 주소 설정이 필요합니다. 실데이터를 조회할 수 없습니다.'
    : status === 'error' ? `서버 조회 실패: ${error ?? '연결을 확인하세요'}. 남아 있는 값은 마지막 서버 응답입니다.`
      : status === 'loading' ? '실서버 데이터를 불러오는 중입니다.'
        : '등록·실행된 데이터가 없습니다. 사일로를 등록하고 정제·학습 작업을 실행하세요.'
  return <p className="silo-observation" role={status === 'error' ? 'alert' : 'status'}>{label}</p>
}
