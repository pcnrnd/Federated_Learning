import { useSimulationStore } from '@/store/useSimulationStore'

/** 시작한 모드의 세대만 화면에 쓸 수 있다. ON→OFF→ON도 별개다. */
export function dataSourceGuard(demo: boolean): () => boolean {
  const generation = useSimulationStore.getState().dataGeneration
  return () => {
    const state = useSimulationStore.getState()
    return state.mockEnabled === demo && state.dataGeneration === generation
  }
}
