import type { Algorithm, NodeState } from '@/types/simulation'

export interface AggregationResult {
  accuracy: number
  loss: number
}

const MAX_ACCURACY = 99.4
const MIN_LOSS = 0.012

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
