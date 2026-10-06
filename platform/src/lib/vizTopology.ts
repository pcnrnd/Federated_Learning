import type { TopologyNodeApi, TopologyPayload, TopologyRole } from '@/api/client'
import { compareSiloId } from '@/api/mappers'

/**
 * 실서버 토폴로지(`/api/visualizations/topology`) → SVG 좌표 (순수 함수).
 * 계층: 중앙 서버 → 그룹 → 사일로 → (집계자 하위) 사일로, 맨 아래 줄에 실행 중 배포.
 * 엣지 클러스터 그룹(멤버 전원이 한 집계자 아래)은 따로 그리지 않고 집계자 노드의 `cluster`로 접는다.
 * x는 잎 노드를 등간격으로 놓고 부모를 자식 범위 가운데에 두는 단순 트리 배치다.
 */
export const VIZ_TOPOLOGY = {
  /** 잎 노드 가로 간격 — 그룹 알약 라벨이 겹치지 않는 폭 */
  gapX: 112,
  /** 계층 세로 간격 */
  rowGap: 96,
  marginX: 64,
  marginTop: 40,
  /** 최하단 노드 라벨 공간 */
  marginBottom: 48,
} as const

/** trunk = 중앙 서버 → 1단(그룹·직결 사일로). 서버 응답에는 없고 계층을 보여주려 그린다 */
export type VizEdgeKind = 'trunk' | 'group' | 'aggregation' | 'deployment'

export interface VizPlacedNode {
  id: string
  label: string
  role: TopologyRole
  x: number
  y: number
  /** 소속 그룹 id (그룹 간선 기준) */
  groups: string[]
  /** 집계자가 맡은 엣지 클러스터 그룹 라벨 (집계자 노드만) */
  cluster: string | null
  overBudget: boolean
}

export interface VizPlacedEdge {
  source: string
  target: string
  kind: VizEdgeKind
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface VizTopologyLayout {
  nodes: VizPlacedNode[]
  edges: VizPlacedEdge[]
  width: number
  height: number
}

/** 중앙 서버가 없을 때 쓰는 보이지 않는 배치용 뿌리 */
const VIRTUAL_ROOT = '__root__'

const byLabel = (a: TopologyNodeApi, b: TopologyNodeApi): number => compareSiloId(a.label, b.label)
const byId = (a: TopologyNodeApi, b: TopologyNodeApi): number => compareSiloId(a.id, b.id)

function collectNodes(payload: TopologyPayload): TopologyNodeApi[] {
  // 간선에만 등장하는 사일로(서버 목록 미등록)도 일반 사일로로 채워 끊긴 선이 없게 한다
  const nodes = new Map(payload.nodes.map((n) => [n.id, n]))
  for (const e of payload.edges) {
    for (const id of [e.source, e.target]) {
      if (!nodes.has(id)) {
        nodes.set(id, { id, label: id, role: 'client', group: null, over_budget: null })
      }
    }
  }
  return [...nodes.values()]
}

/** 집계 간선 → 하위 사일로의 집계자. 먼저 온 간선이 이기고, 순환은 버린다 */
function aggregatorParents(payload: TopologyPayload, siloIds: Set<string>): Map<string, string> {
  const parent = new Map<string, string>()
  const isAncestor = (ancestor: string, id: string): boolean => {
    for (let cur = parent.get(id); cur; cur = parent.get(cur)) if (cur === ancestor) return true
    return false
  }
  for (const e of payload.edges) {
    if (e.kind !== 'aggregation' || e.source === e.target) continue
    if (!siloIds.has(e.source) || !siloIds.has(e.target) || parent.has(e.target)) continue
    if (isAncestor(e.target, e.source)) continue
    parent.set(e.target, e.source)
  }
  return parent
}

/** 멤버가 모두 같은 집계자 아래(또는 그 집계자 자신)인 그룹 → 그 집계자 */
function clusterOwners(
  groupIds: Set<string>,
  payload: TopologyPayload,
  aggParent: Map<string, string>,
): Map<string, string> {
  const members = new Map<string, string[]>()
  for (const e of payload.edges) {
    if (e.kind === 'group' && groupIds.has(e.source)) {
      members.set(e.source, [...(members.get(e.source) ?? []), e.target])
    }
  }
  const owners = new Map<string, string>()
  for (const [groupId, ids] of members) {
    const parents = new Set(ids.flatMap((id) => (aggParent.has(id) ? [aggParent.get(id) as string] : [])))
    const [owner] = parents
    if (parents.size === 1 && ids.every((id) => id === owner || aggParent.get(id) === owner)) {
      owners.set(groupId, owner)
    }
  }
  return owners
}

function depthOf(id: string, aggParent: Map<string, string>): number {
  let depth = 0
  for (let cur = aggParent.get(id); cur; cur = aggParent.get(cur)) depth++
  return depth
}

/** 잎은 등간격, 부모는 첫·끝 자식의 가운데 */
function placeTree(rootId: string, children: Map<string, string[]>): Map<string, number> {
  const x = new Map<string, number>()
  let slot = 0
  const place = (id: string): number => {
    const kids = children.get(id) ?? []
    const xs = kids.map(place)
    const value = xs.length === 0 ? slot++ * VIZ_TOPOLOGY.gapX : (xs[0] + xs[xs.length - 1]) / 2
    x.set(id, value)
    return value
  }
  place(rootId)
  return x
}

/** 배포는 대상 사일로들의 가운데를 원하되, 서로 gapX 이상 떨어지게 오른쪽으로 민다 */
function placeDeployments(
  payload: TopologyPayload,
  deployments: TopologyNodeApi[],
  x: Map<string, number>,
): Map<string, number> {
  const desired = deployments.map((d) => {
    const xs = payload.edges
      .filter((e) => e.kind === 'deployment' && e.source === d.id)
      .flatMap((e) => (x.has(e.target) ? [x.get(e.target) as number] : []))
    return { id: d.id, want: xs.length ? xs.reduce((s, v) => s + v, 0) / xs.length : Infinity }
  })
  desired.sort((a, b) => a.want - b.want)
  const placed = new Map<string, number>()
  let prev = -Infinity
  for (const { id, want } of desired) {
    const next = Number.isFinite(want) ? Math.max(want, prev + VIZ_TOPOLOGY.gapX) : prev + VIZ_TOPOLOGY.gapX
    prev = Number.isFinite(next) ? next : 0
    placed.set(id, prev)
  }
  return placed
}

export function layoutVizTopology(payload: TopologyPayload): VizTopologyLayout {
  const all = collectNodes(payload)
  // ponytail: 중앙 서버는 1대 가정 — 두 번째 central은 사일로 줄에 놓인다
  const central = all.find((n) => n.role === 'central')
  const rootId = central?.id ?? VIRTUAL_ROOT
  const allGroups = all.filter((n) => n.role === 'group').sort(byLabel)
  const deployments = all.filter((n) => n.role === 'deployment').sort(byLabel)
  const silos = all
    .filter((n) => n.id !== rootId && n.role !== 'group' && n.role !== 'deployment')
    .sort(byId)
  const siloIds = new Set(silos.map((n) => n.id))
  const aggParent = aggregatorParents(payload, siloIds)
  const allGroupIds = new Set(allGroups.map((g) => g.id))
  const clusterOf = clusterOwners(allGroupIds, payload, aggParent)
  const groups = allGroups.filter((g) => !clusterOf.has(g.id))
  const groupIds = new Set(groups.map((n) => n.id))
  const clusterLabel = new Map(
    allGroups.filter((g) => clusterOf.has(g.id)).map((g) => [clusterOf.get(g.id) as string, g.label]),
  )

  const memberships = new Map<string, string[]>()
  for (const e of payload.edges) {
    if (e.kind !== 'group' || !allGroupIds.has(e.source) || !siloIds.has(e.target)) continue
    memberships.set(e.target, [...(memberships.get(e.target) ?? []), e.source])
  }

  // 계층 부모: 집계자 > 첫 소속 그룹(클러스터 제외) > 중앙
  const children = new Map<string, string[]>()
  const attach = (id: string, parentId: string) =>
    children.set(parentId, [...(children.get(parentId) ?? []), id])
  for (const g of groups) attach(g.id, rootId)
  for (const s of silos) {
    const group = memberships.get(s.id)?.find((g) => groupIds.has(g))
    attach(s.id, aggParent.get(s.id) ?? group ?? rootId)
  }

  const treeX = placeTree(rootId, children)
  const deployX = placeDeployments(payload, deployments, treeX)

  // 행: 중앙 0 · 그룹 1 · 사일로(그룹이 있으면 2) + 집계 깊이 · 배포는 맨 아래. 중앙이 없으면 한 줄 올린다
  const top = central ? 0 : 1
  const siloBase = groups.length > 0 ? 2 : 1
  const tier = new Map<string, number>()
  if (central) tier.set(rootId, 0)
  for (const g of groups) tier.set(g.id, 1 - top)
  for (const s of silos) tier.set(s.id, siloBase + depthOf(s.id, aggParent) - top)
  const deployTier = Math.max(-1, ...tier.values()) + 1
  for (const d of deployments) tier.set(d.id, deployTier)

  const xOf = (id: string): number =>
    VIZ_TOPOLOGY.marginX + (treeX.get(id) ?? deployX.get(id) ?? 0)
  const yOf = (id: string): number => VIZ_TOPOLOGY.marginTop + (tier.get(id) ?? 0) * VIZ_TOPOLOGY.rowGap

  const ordered = [...(central ? [central] : []), ...groups, ...silos, ...deployments]
  const nodes: VizPlacedNode[] = ordered.map((n) => ({
    id: n.id,
    label: n.label,
    role: n.role,
    x: xOf(n.id),
    y: yOf(n.id),
    groups: memberships.get(n.id) ?? [],
    cluster: clusterLabel.get(n.id) ?? null,
    overBudget: n.over_budget === true,
  }))

  const edge = (source: string, target: string, kind: VizEdgeKind): VizPlacedEdge => ({
    source,
    target,
    kind,
    x1: xOf(source),
    y1: yOf(source),
    x2: xOf(target),
    y2: yOf(target),
  })
  const edges: VizPlacedEdge[] = central
    ? (children.get(rootId) ?? []).map((id) => edge(rootId, id, 'trunk'))
    : []
  for (const e of payload.edges) {
    // 클러스터 그룹의 소속은 집계 간선이 대신 보여준다 (groupIds에서 빠져 있다)
    if (e.kind === 'group' && groupIds.has(e.source) && siloIds.has(e.target)) {
      edges.push(edge(e.source, e.target, 'group'))
    } else if (e.kind === 'aggregation' && aggParent.get(e.target) === e.source) {
      edges.push(edge(e.source, e.target, 'aggregation'))
    } else if (e.kind === 'deployment' && deployX.has(e.source) && treeX.has(e.target)) {
      edges.push(edge(e.source, e.target, 'deployment'))
    }
  }

  const maxX = Math.max(0, ...nodes.map((n) => n.x - VIZ_TOPOLOGY.marginX))
  const maxTier = Math.max(0, ...nodes.map((n) => tier.get(n.id) ?? 0))
  return {
    nodes,
    edges,
    width: maxX + VIZ_TOPOLOGY.marginX * 2,
    height: VIZ_TOPOLOGY.marginTop + maxTier * VIZ_TOPOLOGY.rowGap + VIZ_TOPOLOGY.marginBottom,
  }
}
