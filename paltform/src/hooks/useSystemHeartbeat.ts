import { useEffect, useRef } from 'react'
import { NODE_COUNT, TIMINGS } from '@/constants/simulation'
import { useSimulationStore } from '@/store/useSimulationStore'

/** Idle 상태에서 주기적으로 출력할 시스템 상태 메시지 풀 */
const IDLE_STATUS_MESSAGES = [
  `오케스트레이터 상태 점검: 전 분산 노드 채널 정상 (${NODE_COUNT}/${NODE_COUNT})`,
  '대기 큐 모니터링: 새로운 연합 학습 세션 구성 대기 중...',
  '네트워크 헬스체크: fed-net 토폴로지 연결 상태 양호',
  '리소스 스냅샷: 중앙 집계 서버 CPU·메모리 부하 정상 범위',
  '보안 채널 감시: TLS 핸드셰이크 및 노드 인증서 유효성 확인 완료',
  '스케줄러 폴링: 예약된 연합 라운드 작업 없음 — 사용자 입력 대기',
] as const

/**
 * 시뮬레이션이 실행·일시정지 중이 아닐 때 주기적으로 시스템 로그를 추가한다.
 * Logs 탭에서도 지속적인 터미널 활동감을 제공한다.
 */
export function useSystemHeartbeat(): void {
  const messageIndexRef = useRef(0)

  useEffect(() => {
    const intervalMs = TIMINGS.heartbeatIntervalMs

    const timer = window.setInterval(() => {
      const { isRunning, isPaused } = useSimulationStore.getState()
      if (isRunning && !isPaused) return

      const message = IDLE_STATUS_MESSAGES[messageIndexRef.current % IDLE_STATUS_MESSAGES.length]
      messageIndexRef.current += 1
      useSimulationStore.getState().log('system', message)
    }, intervalMs)

    return () => window.clearInterval(timer)
  }, [])
}
