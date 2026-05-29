import { NODE_COUNT } from '@/constants/simulation'
import type { NodeState } from '@/types/simulation'

export function createInitialNodes(): NodeState[] {
  return Array.from({ length: NODE_COUNT }, (_, i) => {
    const id = i + 1
    const size = Math.floor(Math.random() * 850) + 450
    const delay = Math.floor(Math.random() * 110) + 12
    const mult = 0.95 + Math.random() * 0.1
    const normalPct = Math.floor(Math.random() * 20) + 48
    return {
      id,
      name: `노드 ${id}`,
      size,
      delay,
      mult,
      acc: 0,
      loss: 0,
      cpu: 0,
      status: 'idle',
      normalPct,
      abnormalPct: 100 - normalPct,
    }
  })
}
