import { useDataStore } from '@/store/useDataStore'
import { useModelStore } from '@/store/useModelStore'
import { useSiloStore } from '@/store/useSiloStore'
import { useSimulationStore } from '@/store/useSimulationStore'

/**
 * 목 데이터 스위치의 스토어 오케스트레이션.
 * 스토어끼리는 서로 참조 방향이 고정돼 있어(useSiloStore → useSimulationStore 등)
 * 여기(컴포넌트만 import하는 lib)에서 일괄 처리해야 순환 import가 생기지 않는다.
 */

/** 목 off — 화면의 모든 목 데이터를 비워 "실서버 연동 대기" 상태로 만든다 */
export function clearAllMockData(): void {
  useSimulationStore.getState().clearMockData()
  useSiloStore.getState().clearAll()
  useDataStore.getState().clearAll()
  useModelStore.getState().clearAll()
}

/** 목 on — 초기 데모 시드로 복원한다 (드리프트 임계 등 사용자 설정은 유지) */
export function reseedAllMockData(): void {
  useSimulationStore.getState().reset()
  useSiloStore.getState().reseed()
  useDataStore.getState().reseed()
  useModelStore.getState().reseed()
}
