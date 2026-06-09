import { SILO_SEEDS } from '@/constants/simulation'
import type { NodeState } from '@/types/simulation'

/**
 * 학습 참여 사일로의 초기 런타임 상태 12개를 생성한다.
 * 정체성(id·이름)은 SILO_SEEDS 단일 소스에서 가져오고,
 * 동적 학습 지표(acc/loss/cpu/status)는 0/idle에서 시작한다.
 */
export function createInitialNodes(): NodeState[] {
  return SILO_SEEDS.map((silo) => {
    const size = Math.floor(Math.random() * 850) + 450
    const delay = Math.floor(Math.random() * 110) + 12
    const mult = 0.95 + Math.random() * 0.1
    const normalPct = Math.floor(Math.random() * 20) + 48
    return {
      id: silo.id,
      name: silo.name,
      shortName: silo.shortName,
      size,
      delay,
      mult,
      acc: 0,
      loss: 0,
      cpu: 0,
      status: 'idle',
      normalPct,
      abnormalPct: 100 - normalPct,
      enabled: true,
    }
  })
}
