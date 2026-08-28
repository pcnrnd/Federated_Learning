import { TOPOLOGY } from '@/constants/simulation'
import type { NodeState } from '@/types/simulation'

export interface Point {
  x: number
  y: number
}

/** 좌표가 계산된 노드 하나 */
export interface PlacedNode extends Point {
  node: NodeState
}

/**
 * 계층형 토폴로지 레이아웃 결과.
 * 순수 계산이므로 렌더러(TopologySVG)와 독립적으로 검증할 수 있다.
 */
export interface TopologyLayout {
  /** viewBox 크기 — 1단 사일로 수와 최대 하위 스택 깊이에 따라 확장된다 */
  width: number
  height: number
  server: Point
  /** 중앙 서버 직결 사일로 (좌→우 배치 순) */
  roots: PlacedNode[]
  /** 상위 사일로 아래 세로로 쌓인 하위 노드 */
  children: PlacedNode[]
}

/**
 * 노드 배열로부터 톱다운 트리 좌표를 계산한다.
 *
 * - 1단 사일로는 `siloGapX` 등간격으로 한 줄 배치되고 y는 모두 동일하다.
 * - 하위 노드는 상위 사일로의 x에 정렬되어 아래로 쌓인다.
 * - 하위 노드가 없으면 height는 1단 기준 높이로 유지된다.
 */
export function computeLayout(nodes: readonly NodeState[]): TopologyLayout {
  const rootNodes = nodes.filter((n) => n.parentId === undefined)

  const roots: PlacedNode[] = rootNodes.map((node, index) => ({
    node,
    x: Math.round(TOPOLOGY.marginX + (index + 0.5) * TOPOLOGY.siloGapX),
    y: TOPOLOGY.siloY,
  }))

  const children: PlacedNode[] = []
  let maxDepth = 0

  roots.forEach((root) => {
    const own = nodes.filter((n) => n.parentId === root.node.id)
    own.forEach((node, index) => {
      children.push({
        node,
        x: root.x,
        y: TOPOLOGY.siloY + (index + 1) * TOPOLOGY.childGapY,
      })
    })
    maxDepth = Math.max(maxDepth, own.length)
  })

  const width = TOPOLOGY.marginX * 2 + roots.length * TOPOLOGY.siloGapX

  return {
    width,
    height: TOPOLOGY.siloY + maxDepth * TOPOLOGY.childGapY + TOPOLOGY.marginBottom,
    server: { x: Math.round(width / 2), y: TOPOLOGY.serverY },
    roots,
    children,
  }
}

/**
 * 사일로 → 중앙 서버 연결선 (cubic bezier).
 * 패킷 애니메이션이 기존 keyPoints 규약을 그대로 쓰도록 사일로에서 시작해 서버로 끝난다.
 */
export function pathFromSiloToServer(silo: Point, server: Point): string {
  const half = (silo.y - server.y) / 2
  return `M ${silo.x} ${silo.y} C ${silo.x} ${silo.y - half}, ${server.x} ${server.y + half}, ${server.x} ${server.y}`
}

/** 하위 노드 → 상위 사일로 연결선 (짧은 수직 직선) */
export function pathFromChildToParent(child: Point, parent: Point): string {
  return `M ${child.x} ${child.y} L ${parent.x} ${parent.y}`
}
