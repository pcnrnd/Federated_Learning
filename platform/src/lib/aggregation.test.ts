import { describe, expect, test } from 'vitest'
import { aggregate, aggregateHierarchy, effectiveEnabledNodes } from '@/lib/aggregation'
import type { NodeState } from '@/types/simulation'

interface NodeOverrides {
  id: number
  size: number
  acc: number
  loss: number
  parentId?: number
  enabled?: boolean
  pending?: boolean
}

function node({
  id,
  size,
  acc,
  loss,
  parentId,
  enabled = true,
  pending = false,
}: NodeOverrides): NodeState {
  return {
    id,
    name: `노드${id}`,
    shortName: `노드${id}`,
    size,
    delay: 20,
    mult: 1,
    acc,
    loss,
    cpu: 0,
    status: 'idle',
    normalPct: 50,
    abnormalPct: 50,
    enabled,
    pending,
    ...(parentId !== undefined ? { parentId } : {}),
  }
}

describe('effectiveEnabledNodes', () => {
  test('excludes a child whose parent silo is disabled', () => {
    // Arrange: 상위(1) 비활성, 그 하위(11)는 자체적으로는 활성
    const nodes = [
      node({ id: 1, size: 100, acc: 80, loss: 1, enabled: false }),
      node({ id: 11, size: 300, acc: 40, loss: 2, parentId: 1 }),
      node({ id: 2, size: 200, acc: 90, loss: 0.5 }),
    ]

    // Act
    const active = effectiveEnabledNodes(nodes)

    // Assert: 서버까지 경로가 끊겼으므로 하위도 라운드에서 빠진다
    expect(active.map((n) => n.id)).toEqual([2])
  })

  test('keeps a child when both it and its parent are enabled', () => {
    const nodes = [
      node({ id: 1, size: 100, acc: 80, loss: 1 }),
      node({ id: 11, size: 300, acc: 40, loss: 2, parentId: 1 }),
    ]

    expect(effectiveEnabledNodes(nodes).map((n) => n.id)).toEqual([1, 11])
  })

  test('excludes a child that is disabled on its own', () => {
    const nodes = [
      node({ id: 1, size: 100, acc: 80, loss: 1 }),
      node({ id: 11, size: 300, acc: 40, loss: 2, parentId: 1, enabled: false }),
    ]

    expect(effectiveEnabledNodes(nodes).map((n) => n.id)).toEqual([1])
  })

  test('excludes a node registered mid-round until the next round releases it', () => {
    const nodes = [
      node({ id: 1, size: 100, acc: 80, loss: 1 }),
      node({ id: 11, size: 300, acc: 0, loss: 0, parentId: 1, pending: true }),
    ]

    expect(effectiveEnabledNodes(nodes).map((n) => n.id)).toEqual([1])
  })

  test('excludes children of a pending parent as well', () => {
    const nodes = [
      node({ id: 1, size: 100, acc: 0, loss: 0, pending: true }),
      node({ id: 11, size: 300, acc: 0, loss: 0, parentId: 1 }),
    ]

    expect(effectiveEnabledNodes(nodes)).toEqual([])
  })
})

describe('aggregateHierarchy', () => {
  test('weights child parameters by data size in the edge stage', () => {
    // Arrange
    //  사일로1(size 100, acc 80, loss 1.0) + 하위11(size 300, acc 40, loss 2.0)
    //    → 엣지 집계: acc (80*100 + 40*300)/400 = 50, loss (1*100 + 2*300)/400 = 1.75, size 400
    //  사일로2(size 200, acc 90, loss 0.5) — 하위 없음, 그대로 통과
    //    → 글로벌: acc (50*400 + 90*200)/600 = 190/3, loss (1.75*400 + 0.5*200)/600 = 4/3
    const nodes = [
      node({ id: 1, size: 100, acc: 80, loss: 1 }),
      node({ id: 11, size: 300, acc: 40, loss: 2, parentId: 1 }),
      node({ id: 2, size: 200, acc: 90, loss: 0.5 }),
    ]

    // Act
    const result = aggregateHierarchy(nodes, 'fedavg')

    // Assert
    expect(result.accuracy).toBeCloseTo(190 / 3, 10)
    expect(result.loss).toBeCloseTo(4 / 3, 10)
  })

  test('matches flat aggregation when no child nodes exist', () => {
    const nodes = [
      node({ id: 1, size: 100, acc: 80, loss: 1 }),
      node({ id: 2, size: 200, acc: 90, loss: 0.5 }),
    ]

    expect(aggregateHierarchy(nodes, 'fedavg')).toEqual(aggregate(nodes, 'fedavg'))
  })

  test('drops a disabled parent together with its children', () => {
    // Arrange: 사일로1 비활성 → 사일로1과 하위11이 모두 빠지고 사일로2만 남는다
    const nodes = [
      node({ id: 1, size: 100, acc: 10, loss: 9, enabled: false }),
      node({ id: 11, size: 300, acc: 10, loss: 9, parentId: 1 }),
      node({ id: 2, size: 200, acc: 90, loss: 0.5 }),
    ]

    const result = aggregateHierarchy(nodes, 'fedavg')

    expect(result.accuracy).toBeCloseTo(90, 10)
    expect(result.loss).toBeCloseTo(0.5, 10)
  })

  test('falls back to every node when all are disabled', () => {
    // 전원 비활성이어도 NaN 대신 마지막 지표를 유지해야 한다
    const nodes = [
      node({ id: 1, size: 100, acc: 60, loss: 1, enabled: false }),
      node({ id: 2, size: 100, acc: 80, loss: 2, enabled: false }),
    ]

    const result = aggregateHierarchy(nodes, 'fedavg')

    expect(result.accuracy).toBeCloseTo(70, 10)
    expect(result.loss).toBeCloseTo(1.5, 10)
  })

  test('returns zeros for an empty node set instead of NaN', () => {
    expect(aggregateHierarchy([], 'fedavg')).toEqual({ accuracy: 0, loss: 0 })
  })

  test('keeps an untrained mid-round arrival out of the global average', () => {
    // Arrange: 라운드 도중 증설된 노드11은 학습 이력이 없어 acc=0 — 끼면 평균을 끌어내린다
    const trained = [
      node({ id: 1, size: 100, acc: 80, loss: 1 }),
      node({ id: 2, size: 100, acc: 80, loss: 1 }),
    ]
    const withArrival = [
      ...trained,
      node({ id: 11, size: 900, acc: 0, loss: 0, parentId: 1, pending: true }),
    ]

    // Act / Assert: 대기 노드는 이번 라운드 집계에 영향을 주지 않는다
    expect(aggregateHierarchy(withArrival, 'fedavg')).toEqual(
      aggregateHierarchy(trained, 'fedavg'),
    )
  })
})
