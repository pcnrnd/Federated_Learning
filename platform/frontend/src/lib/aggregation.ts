import type { Algorithm, NodeState } from '@/types/simulation'

export interface AggregationResult {
  accuracy: number
  loss: number
}

const MAX_ACCURACY = 99.4
const MIN_LOSS = 0.012

/**
 * 실제로 이번 라운드에 참여하는 노드만 추린다.
 * - 비활성 노드는 제외한다.
 * - 하위 노드는 상위 사일로가 비활성이면 서버까지 경로가 끊기므로 함께 제외된다.
 * - 라운드 도중 증설된 대기(`pending`) 노드는 다음 라운드까지 제외된다.
 * 학습·상태 전환·집계의 참여 판정은 전부 이 헬퍼를 기준으로 통일한다.
 */
export function effectiveEnabledNodes(nodes: readonly NodeState[]): NodeState[] {
  const isParticipating = (n: NodeState): boolean => n.enabled && !n.pending
  const activeIds = new Set(nodes.filter(isParticipating).map((n) => n.id))
  return nodes.filter(
    (n) => isParticipating(n) && (n.parentId === undefined || activeIds.has(n.parentId)),
  )
}

export function aggregate(nodes: readonly NodeState[], algorithm: Algorithm): AggregationResult {
  const { sumAcc, sumLoss, totalWeight } = nodes.reduce(
    (acc, node) => ({
      sumAcc: acc.sumAcc + node.acc * node.size,
      sumLoss: acc.sumLoss + node.loss * node.size,
      totalWeight: acc.totalWeight + node.size,
    }),
    { sumAcc: 0, sumLoss: 0, totalWeight: 0 },
  )

  let rawAcc = sumAcc / totalWeight
  let rawLoss = sumLoss / totalWeight

  if (algorithm === 'fedmedian') {
    rawAcc = rawAcc - 0.65 + Math.random() * 0.4
    rawLoss = rawLoss + 0.015 + Math.random() * 0.01
  }

  return {
    accuracy: Math.min(MAX_ACCURACY, rawAcc),
    loss: Math.max(MIN_LOSS, rawLoss),
  }
}

/**
 * 계층형 연합학습(HFL) 2단계 집계.
 *
 * ① 하위 노드 → 상위 사일로: 데이터 크기(`size`) 가중평균으로 엣지 집계.
 * ② 엣지 집계 결과를 가진 1단 사일로 → 중앙 서버: 기존 `aggregate()`로 글로벌 집계.
 *
 * 하위 노드가 하나도 없으면 ①이 항등 변환이므로 기존 단일 계층 동작과 동일하다.
 */
export function aggregateHierarchy(
  nodes: readonly NodeState[],
  algorithm: Algorithm,
): AggregationResult {
  const active = effectiveEnabledNodes(nodes)
  // 전원 비활성이면 마지막 지표를 유지하기 위해 전체 노드로 폴백한다
  const pool = active.length > 0 ? active : nodes
  if (pool.length === 0) return { accuracy: 0, loss: 0 }

  const edgeAggregated = pool
    .filter((n) => n.parentId === undefined)
    .map((root) => {
      const members = [root, ...pool.filter((n) => n.parentId === root.id)]
      if (members.length === 1) return root

      const totalWeight = members.reduce((sum, m) => sum + m.size, 0)
      return {
        ...root,
        acc: members.reduce((sum, m) => sum + m.acc * m.size, 0) / totalWeight,
        loss: members.reduce((sum, m) => sum + m.loss * m.size, 0) / totalWeight,
        // 상위 사일로는 하위를 대표하므로 글로벌 집계에서 그만큼의 가중치를 갖는다
        size: totalWeight,
      }
    })

  // 1단이 전부 비활성이고 하위만 살아있는 구성은 나올 수 없지만(경로 단절), 방어적으로 폴백
  return aggregate(edgeAggregated.length > 0 ? edgeAggregated : pool, algorithm)
}

export interface EpochProgress {
  currentRound: number
  totalRounds: number
  epoch: number
  totalEpochs: number
}

const INITIAL_NODE_ACC_BASELINE = 28
const INITIAL_NODE_LOSS_BASELINE = 2.1

export function computeNodeEpochMetrics(
  node: NodeState,
  progress: EpochProgress,
): { acc: number; loss: number } {
  const roundProgress = progress.currentRound / progress.totalRounds
  const prevRoundProgress = (progress.currentRound - 1) / progress.totalRounds
  const epochProgress = progress.epoch / progress.totalEpochs

  const targetAcc = 45 + 42 * Math.pow(roundProgress, 0.5) * node.mult
  const startAcc =
    progress.currentRound === 1
      ? INITIAL_NODE_ACC_BASELINE
      : 45 + 42 * Math.pow(prevRoundProgress, 0.5) * node.mult

  const stepAcc = startAcc + (targetAcc - startAcc) * epochProgress
  const accJitter = (Math.random() - 0.5) * 1.5
  const acc = Math.min(98.5, Math.max(20.0, stepAcc + accJitter))

  const targetLoss = 0.15 + (1.9 * (1 - Math.pow(roundProgress, 0.6))) / node.mult
  const startLoss =
    progress.currentRound === 1
      ? INITIAL_NODE_LOSS_BASELINE
      : 0.15 + (1.9 * (1 - Math.pow(prevRoundProgress, 0.6))) / node.mult

  const stepLoss = startLoss + (targetLoss - startLoss) * epochProgress
  const loss = Math.max(0.02, stepLoss + (Math.random() - 0.5) * 0.05)

  return { acc, loss }
}
