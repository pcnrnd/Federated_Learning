import type { VizEdgeKind, VizPlacedNode, VizTopologyLayout } from '@/lib/vizTopology'
import { siloColorVar } from '@/lib/chartTheme'

const EDGE_LEGEND: Array<{ kind: VizEdgeKind; label: string }> = [
  { kind: 'trunk', label: '중앙 연결' },
  { kind: 'group', label: '그룹 소속' },
  { kind: 'aggregation', label: '집계자 경유' },
  { kind: 'deployment', label: '실행 중 배포' },
]

const SILO_RADIUS = 14
const AGGREGATOR_RADIUS = 16
const CENTRAL_RADIUS = 20
const PILL_HEIGHT = 24

/** 알약 노드 폭 — 글자 수에 비례, 최소 72 */
const pillWidth = (text: string): number => Math.max(72, text.length * 7 + 20)
const truncate = (text: string, max: number): string =>
  text.length > max ? `${text.slice(0, max - 1)}…` : text

function nodeTitle(n: VizPlacedNode): string {
  const lines = [n.role === 'group' || n.label === n.id ? n.label : `${n.label} (${n.id})`]
  if (n.groups.length) lines.push(`그룹: ${n.groups.map((g) => g.replace(/^group::/, '')).join(', ')}`)
  if (n.role === 'aggregator') lines.push(n.cluster ? `엣지 클러스터 ${n.cluster} 집계 담당` : '하위 사일로 집계 담당')
  if (n.overBudget) lines.push('자원 한도 초과')
  return lines.join('\n')
}

interface PillProps {
  text: string
  className: string
}

function Pill({ text, className }: PillProps) {
  const w = pillWidth(text)
  return (
    <>
      <rect className={className} x={-w / 2} y={-PILL_HEIGHT / 2} width={w} height={PILL_HEIGHT} rx={PILL_HEIGHT / 2} />
      <text className="viz-node-pill-text" y={4} textAnchor="middle">
        {text}
      </text>
    </>
  )
}

interface NodeShapeProps {
  node: VizPlacedNode
}

function NodeShape({ node }: NodeShapeProps) {
  if (node.role === 'group') return <Pill text={truncate(node.label, 16)} className="viz-node-group" />
  if (node.role === 'deployment') return <Pill text={truncate(node.label, 18)} className="viz-node-deploy" />

  const isCentral = node.role === 'central'
  const isAggregator = node.role === 'aggregator'
  const r = isCentral ? CENTRAL_RADIUS : isAggregator ? AGGREGATOR_RADIUS : SILO_RADIUS
  return (
    <>
      {isAggregator && <circle className="viz-node-aggregator-ring" r={r + 5} />}
      <circle
        className={`viz-node-dot${isCentral ? ' viz-node-central' : ''}${node.overBudget ? ' over-budget' : ''}`}
        r={r}
        style={isCentral ? undefined : { fill: siloColorVar(node.id) }}
      />
      <text className="viz-node-label" y={r + 16} textAnchor="middle">
        {isCentral ? node.label : node.id}
      </text>
      {isAggregator && (
        <text className="viz-node-sublabel" y={r + 29} textAnchor="middle">
          {node.cluster ? `집계자 · ${truncate(node.cluster, 12)}` : '집계자'}
        </text>
      )}
    </>
  )
}

interface LiveTopologyProps {
  layout: VizTopologyLayout
}

/** 실서버 연합 구성: 중앙 서버 → 그룹 → 집계자 → 사일로, 실행 중 배포 */
export function LiveTopology({ layout }: LiveTopologyProps) {
  return (
    <>
      <div className="viz-legend" aria-label="연결 범례">
        {EDGE_LEGEND.map(({ kind, label }) => (
          <span key={kind} className="viz-legend-item">
            <svg width="24" height="8" aria-hidden="true">
              <line className={`viz-edge viz-edge--${kind}`} x1="0" y1="4" x2="24" y2="4" />
            </svg>
            {label}
          </span>
        ))}
      </div>
      <div className="viz-topology">
        <svg
          width={layout.width}
          height={layout.height}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          role="img"
          aria-label="연합 토폴로지"
        >
          {layout.edges.map((e) => (
            <line
              key={`${e.kind}:${e.source}>${e.target}`}
              className={`viz-edge viz-edge--${e.kind}`}
              x1={e.x1}
              y1={e.y1}
              x2={e.x2}
              y2={e.y2}
            />
          ))}
          {layout.nodes.map((n) => (
            <g key={n.id} className="viz-node" transform={`translate(${n.x} ${n.y})`}>
              <title>{nodeTitle(n)}</title>
              <NodeShape node={n} />
            </g>
          ))}
        </svg>
      </div>
    </>
  )
}
