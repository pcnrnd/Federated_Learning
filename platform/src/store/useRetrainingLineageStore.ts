import { create } from 'zustand'
import { isLiveConfigured } from '@/api/client'
import { fetchLineage, lineageKey, type LineageKind } from '@/api/retrainingLineage'
import { useSimulationStore } from './useSimulationStore'

interface LineageDetail { pending: boolean; lines: string[]; error: string | null }
interface LineageState {
  entries: Record<string, LineageDetail>
  generation: number
  load: (kind: LineageKind, id: string) => Promise<void>
}
export const useRetrainingLineageStore = create<LineageState>((set, get) => ({
  entries: {}, generation: 0,
  load: async (kind, id) => {
    if (useSimulationStore.getState().mockEnabled || !isLiveConfigured()) return
    const key = lineageKey(kind, id)
    if (get().entries[key]?.pending) return
    const epoch = get().generation
    const current = () => !useSimulationStore.getState().mockEnabled && epoch === get().generation
    set((s) => ({ entries: { ...s.entries, [key]: { pending: true, lines: [], error: null } } }))
    try {
      const lines = await fetchLineage(kind, id)
      if (current()) set((s) => ({ entries: { ...s.entries, [key]: { pending: false, lines, error: null } } }))
    } catch {
      if (current()) set((s) => ({ entries: { ...s.entries, [key]: { pending: false, lines: [], error: '상세 조회에 실패했습니다. 서버 연결과 접근 권한을 확인하세요.' } } }))
    }
  },
}))
useSimulationStore.subscribe((state, previous) => {
  if (state.mockEnabled !== previous.mockEnabled) {
    useRetrainingLineageStore.setState((s) => ({ entries: {}, generation: s.generation + 1 }))
  }
})
