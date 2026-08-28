import { describe, expect, test } from 'vitest'
import { TOPOLOGY } from '@/constants/simulation'
import { computeLayout } from '@/lib/topology'
import type { NodeState } from '@/types/simulation'

function node(id: number, parentId?: number): NodeState {
  return {
    id,
    name: `노드${id}`,
    shortName: `노드${id}`,
    size: 1000,
    delay: 20,
    mult: 1,
    acc: 0,
    loss: 0,
    cpu: 0,
    status: 'idle',
    normalPct: 50,
    abnormalPct: 50,
    enabled: true,
    ...(parentId !== undefined ? { parentId } : {}),
  }
}

const twelveRoots = Array.from({ length: 12 }, (_, i) => node(i + 1))

describe('computeLayout', () => {
  test('places all 1단 사일로 on one row at equal spacing', () => {
    // Arrange / Act
    const layout = computeLayout(twelveRoots)

    // Assert
    expect(layout.roots).toHaveLength(12)
    expect(new Set(layout.roots.map((r) => r.y))).toEqual(new Set([TOPOLOGY.siloY]))

    const gaps = layout.roots.slice(1).map((r, i) => r.x - layout.roots[i].x)
    expect(new Set(gaps)).toEqual(new Set([TOPOLOGY.siloGapX]))
  })

  test('centers the server horizontally over the silo row', () => {
    const layout = computeLayout(twelveRoots)

    expect(layout.server).toEqual({
      x: Math.round(layout.width / 2),
      y: TOPOLOGY.serverY,
    })
  })

  test('aligns child nodes to the parent x and stacks them downward', () => {
    // Arrange: 사일로3 아래에 하위 노드 2개
    const nodes = [...twelveRoots, node(13, 3), node(14, 3)]

    // Act
    const layout = computeLayout(nodes)

    // Assert
    const parent = layout.roots.find((r) => r.node.id === 3)!
    const children = layout.children.filter((c) => c.node.parentId === 3)

    expect(children.map((c) => c.x)).toEqual([parent.x, parent.x])
    expect(children.map((c) => c.y)).toEqual([
      TOPOLOGY.siloY + TOPOLOGY.childGapY,
      TOPOLOGY.siloY + 2 * TOPOLOGY.childGapY,
    ])
  })

  test('expands viewBox height by the deepest child stack only', () => {
    const flat = computeLayout(twelveRoots)
    // 사일로1에 1개, 사일로2에 3개 → 최대 깊이 3
    const deep = computeLayout([
      ...twelveRoots,
      node(13, 1),
      node(14, 2),
      node(15, 2),
      node(16, 2),
    ])

    expect(flat.height).toBe(TOPOLOGY.siloY + TOPOLOGY.marginBottom)
    expect(deep.height).toBe(flat.height + 3 * TOPOLOGY.childGapY)
    // 하위 노드는 부모 열 안에 쌓이므로 가로 폭은 그대로다
    expect(deep.width).toBe(flat.width)
  })

  test('keeps width proportional to the 1단 사일로 count', () => {
    const layout = computeLayout(twelveRoots)

    expect(layout.width).toBe(TOPOLOGY.marginX * 2 + 12 * TOPOLOGY.siloGapX)
  })
})
