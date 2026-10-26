import { describe, expect, test } from 'vitest'
import type { TopologyEdgeApi, TopologyNodeApi, TopologyRole } from '@/api/client'
import { VIZ_TOPOLOGY, layoutVizTopology, vizLegendKinds } from '@/lib/vizTopology'

const { gapX, rowGap, marginX, marginTop } = VIZ_TOPOLOGY

function node(id: string, role: TopologyRole = 'client'): TopologyNodeApi {
  return { id, label: id, role, group: null, over_budget: null }
}

function edge(source: string, target: string, kind: TopologyEdgeApi['kind']): TopologyEdgeApi {
  return { source, target, kind, metadata: {} }
}

const central = node('main', 'central')
const group = (id: string): TopologyNodeApi => ({ ...node(`group::${id}`, 'group'), label: id })

describe('layoutVizTopology', () => {
  test('lays out central → group → silos with silos evenly spaced on one row', () => {
    // Arrange
    const payload = {
      nodes: [central, node('silo-2'), node('silo-1'), node('silo-3'), group('g')],
      edges: ['silo-1', 'silo-2', 'silo-3'].map((s) => edge('group::g', s, 'group')),
    }

    // Act
    const layout = layoutVizTopology(payload)
    const at = (id: string) => layout.nodes.find((n) => n.id === id)!

    // Assert: 사일로는 id 순 등간격, 그룹·중앙은 자식 가운데
    expect(['silo-1', 'silo-2', 'silo-3'].map((id) => at(id).x)).toEqual([
      marginX,
      marginX + gapX,
      marginX + gapX * 2,
    ])
    expect(at('silo-1').y).toBe(marginTop + rowGap * 2)
    expect(at('group::g')).toMatchObject({ x: marginX + gapX, y: marginTop + rowGap })
    expect(at('main')).toMatchObject({ x: marginX + gapX, y: marginTop })
    expect(at('silo-2').groups).toEqual(['group::g'])
    expect(layout.edges.map((e) => e.kind)).toEqual(['trunk', 'group', 'group', 'group'])
    expect(layout.width).toBe(gapX * 2 + marginX * 2)
  })

  test('puts aggregator members one row below and folds the edge-cluster group into the aggregator', () => {
    // Arrange: 루트 그룹 g(silo-1, silo-2) + 엣지 클러스터 edge-a(silo-3, silo-4, 집계자 silo-2)
    const payload = {
      nodes: [
        central,
        node('silo-1'),
        node('silo-2', 'aggregator'),
        node('silo-3'),
        node('silo-4'),
        group('g'),
        group('edge-a'),
      ],
      edges: [
        edge('group::g', 'silo-1', 'group'),
        edge('group::g', 'silo-2', 'group'),
        edge('group::edge-a', 'silo-3', 'group'),
        edge('group::edge-a', 'silo-4', 'group'),
        edge('silo-2', 'silo-3', 'aggregation'),
        edge('silo-2', 'silo-4', 'aggregation'),
      ],
    }

    // Act
    const layout = layoutVizTopology(payload)
    const at = (id: string) => layout.nodes.find((n) => n.id === id)!

    // Assert
    expect(at('silo-2')).toMatchObject({ role: 'aggregator', cluster: 'edge-a' })
    expect(layout.nodes.some((n) => n.id === 'group::edge-a')).toBe(false)
    expect(at('silo-3').y - at('silo-2').y).toBe(rowGap)
    expect(at('silo-2').x).toBe((at('silo-3').x + at('silo-4').x) / 2)
    expect(at('silo-3').groups).toEqual(['group::edge-a'])
    expect(layout.edges.map((e) => `${e.kind}:${e.source}>${e.target}`)).toEqual([
      'trunk:main>group::g',
      'group:group::g>silo-1',
      'group:group::g>silo-2',
      'aggregation:silo-2>silo-3',
      'aggregation:silo-2>silo-4',
    ])
  })

  test('keeps a group as a node when its members are not all under one aggregator', () => {
    const payload = {
      nodes: [central, node('silo-1'), node('silo-2', 'aggregator'), node('silo-3'), group('mixed')],
      edges: [
        edge('group::mixed', 'silo-1', 'group'),
        edge('group::mixed', 'silo-3', 'group'),
        edge('silo-2', 'silo-3', 'aggregation'),
      ],
    }

    const layout = layoutVizTopology(payload)

    expect(layout.nodes.find((n) => n.id === 'group::mixed')).toBeDefined()
    expect(layout.nodes.find((n) => n.id === 'silo-2')!.cluster).toBeNull()
  })

  test('places running deployments on the bottom row centred over their targets', () => {
    const payload = {
      nodes: [central, node('silo-1'), node('silo-2'), node('deploy::abc', 'deployment')],
      edges: [edge('deploy::abc', 'silo-1', 'deployment'), edge('deploy::abc', 'silo-2', 'deployment')],
    }

    const layout = layoutVizTopology(payload)
    const deploy = layout.nodes.find((n) => n.id === 'deploy::abc')!

    // 그룹 없음 → 사일로가 1행, 배포는 2행
    expect(deploy.y).toBe(marginTop + rowGap * 2)
    expect(deploy.x).toBe(marginX + gapX / 2)
    expect(layout.edges.filter((e) => e.kind === 'deployment')).toHaveLength(2)
  })

  test('spreads deployments that want the same spot', () => {
    const payload = {
      nodes: [central, node('silo-1'), node('deploy::a', 'deployment'), node('deploy::b', 'deployment')],
      edges: [edge('deploy::a', 'silo-1', 'deployment'), edge('deploy::b', 'silo-1', 'deployment')],
    }

    const xs = layoutVizTopology(payload)
      .nodes.filter((n) => n.role === 'deployment')
      .map((n) => n.x)

    expect(Math.abs(xs[0] - xs[1])).toBe(gapX)
  })

  test('adds silos that appear only in edges and marks over-budget nodes', () => {
    const payload = {
      nodes: [central, { ...node('silo-1'), over_budget: true }, group('g')],
      edges: [edge('group::g', 'silo-1', 'group'), edge('group::g', 'silo-9', 'group')],
    }

    const layout = layoutVizTopology(payload)

    expect(layout.nodes.find((n) => n.id === 'silo-9')).toMatchObject({ role: 'client', label: 'silo-9' })
    expect(layout.nodes.find((n) => n.id === 'silo-1')!.overBudget).toBe(true)
  })

  test('without a central server starts at the top row and draws no trunk edges', () => {
    const layout = layoutVizTopology({
      nodes: [node('silo-1'), group('g')],
      edges: [edge('group::g', 'silo-1', 'group')],
    })

    expect(layout.nodes.find((n) => n.id === 'group::g')!.y).toBe(marginTop)
    expect(layout.edges.map((e) => e.kind)).toEqual(['group'])
  })

  test('ignores aggregation cycles instead of looping', () => {
    const layout = layoutVizTopology({
      nodes: [central, node('silo-1', 'aggregator'), node('silo-2', 'aggregator')],
      edges: [edge('silo-1', 'silo-2', 'aggregation'), edge('silo-2', 'silo-1', 'aggregation')],
    })

    expect(layout.edges.filter((e) => e.kind === 'aggregation')).toHaveLength(1)
  })

  test('returns an empty layout for an empty payload', () => {
    const layout = layoutVizTopology({ nodes: [], edges: [] })
    expect(layout.nodes).toEqual([])
    expect(layout.edges).toEqual([])
  })
})

describe('vizLegendKinds', () => {
  test('lists only the edge kinds that are drawn, in legend order', () => {
    const layout = layoutVizTopology({
      nodes: [central, node('silo-1'), node('silo-2'), group('g'), node('deploy::a', 'deployment')],
      edges: [
        edge('deploy::a', 'silo-1', 'deployment'),
        edge('group::g', 'silo-1', 'group'),
        edge('group::g', 'silo-2', 'group'),
      ],
    })

    expect(vizLegendKinds(layout.edges)).toEqual(['trunk', 'group', 'deployment'])
  })

  test('omits running deployments when the response has none', () => {
    const layout = layoutVizTopology({
      nodes: [central, node('silo-1'), group('g')],
      edges: [edge('group::g', 'silo-1', 'group')],
    })

    expect(vizLegendKinds(layout.edges)).toEqual(['trunk', 'group'])
  })

  test('omits the central link without a central server', () => {
    const layout = layoutVizTopology({
      nodes: [node('silo-1', 'aggregator'), node('silo-2'), group('g')],
      edges: [edge('group::g', 'silo-1', 'group'), edge('silo-1', 'silo-2', 'aggregation')],
    })

    expect(vizLegendKinds(layout.edges)).toEqual(['group', 'aggregation'])
  })

  test('omits group membership when the only group is folded into its aggregator', () => {
    const layout = layoutVizTopology({
      nodes: [central, node('silo-1', 'aggregator'), node('silo-2'), group('edge-a')],
      edges: [edge('group::edge-a', 'silo-2', 'group'), edge('silo-1', 'silo-2', 'aggregation')],
    })

    expect(vizLegendKinds(layout.edges)).toEqual(['trunk', 'aggregation'])
  })

  test('is empty for an empty payload', () => {
    expect(vizLegendKinds(layoutVizTopology({ nodes: [], edges: [] }).edges)).toEqual([])
  })
})
