import { SILO_SEEDS } from '@/constants/simulation'
import type { NodeState } from '@/types/simulation'

export interface NodeIdentity {
  id: number
  name: string
  shortName: string
  /** 상위 사일로 id. 생략하면 1단 사일로 */
  parentId?: number
}

/**
 * 학습 참여자 한 명의 초기 런타임 상태를 만든다.
 * 정체성(id·이름·상위)은 호출자가 주고, 동적 학습 지표는 0/idle에서 시작하며
 * 데이터 크기·지연·학습 계수는 목 시뮬레이션용 난수로 채운다.
 * 1단 사일로와 하위 노드가 같은 규칙을 공유한다.
 */
export function createNode(identity: NodeIdentity): NodeState {
  const normalPct = Math.floor(Math.random() * 20) + 48
  return {
    id: identity.id,
    name: identity.name,
    shortName: identity.shortName,
    size: Math.floor(Math.random() * 850) + 450,
    delay: Math.floor(Math.random() * 110) + 12,
    mult: 0.95 + Math.random() * 0.1,
    acc: 0,
    loss: 0,
    cpu: 0,
    status: 'idle',
    normalPct,
    abnormalPct: 100 - normalPct,
    enabled: true,
    ...(identity.parentId !== undefined ? { parentId: identity.parentId } : {}),
  }
}

/**
 * 중앙 서버에 직결된 1단 사일로(SILO_SEEDS)의 초기 상태를 생성한다.
 * 정체성은 SILO_SEEDS 단일 소스에서 가져온다.
 */
export function createInitialNodes(): NodeState[] {
  return SILO_SEEDS.map((silo) =>
    createNode({ id: silo.id, name: silo.name, shortName: silo.shortName }),
  )
}
