import { isLiveConfigured } from '@/api/client'
import { useSimulationStore } from '@/store/useSimulationStore'

export function DataSourceStatus() {
  const demo = useSimulationStore((s) => s.mockEnabled)
  const status = useSimulationStore((s) => s.liveStatus)
  const error = useSimulationStore((s) => s.liveError)
  if (demo) return <p className="silo-observation" role="status">데모 데이터 · 화면 안의 예시이며 서버는 변경하지 않습니다.</p>
  const label = !isLiveConfigured() ? '실데이터 API 주소 설정이 필요합니다. 실데이터를 조회할 수 없습니다.'
    : status === 'error' ? `서버 조회 실패: ${error ?? '연결을 확인하세요'}. 남아 있는 값은 마지막 서버 응답입니다.`
      : status === 'loading' ? '실서버 데이터를 불러오는 중입니다.'
        : status === 'empty' ? '서버가 빈 목록을 반환했습니다. 등록·실행된 실제 데이터가 없습니다.'
          : '실서버 데이터 · 서버가 반환한 기존 기록을 표시합니다.'
  return <p className="silo-observation" role={status === 'error' ? 'alert' : 'status'}>{label}</p>
}
