import { useMemo, useRef, useState } from 'react'
import { TOPOLOGY, TOPOLOGY_ZOOM } from '@/constants/simulation'
import { effectiveEnabledNodes } from '@/lib/aggregation'
import {
  computeLayout,
  pathFromChildToParent,
  pathFromSiloToServer,
  type PlacedNode,
} from '@/lib/topology'
import { deriveStorageUnits, type StorageUnit } from '@/lib/storage'
import { useDataStore, type SiloDataFields } from '@/store/useDataStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { NodeStatus, PacketDirection } from '@/types/simulation'

/** 패킷이 흐르는 방향에 따라 경로를 활성화한다. 서버↔사일로 구간(WAN)만 반응. */
function trunkPathClass(direction: PacketDirection): string {
  if (direction === 'download') return 'network-path active-download'
  if (direction === 'upload') return 'network-path active-upload'
  return 'network-path'
}

/** 사일로↔하위 노드 구간(엣지)만 반응 — 전역 direction을 경로별로 분기한다. */
function edgePathClass(direction: PacketDirection): string {
  if (direction === 'edge-download') return 'network-path edge-path active-download'
  if (direction === 'edge-upload') return 'network-path edge-path active-upload'
  return 'network-path edge-path'
}

function clientNodeClass(status: NodeStatus, active: boolean): string {
  if (!active) return 'client-node node-off'
  if (status === 'syncing') return 'client-node active-sync'
  if (status === 'training') return 'client-node active-local'
  if (status === 'uploading') return 'client-node active-upload'
  if (status === 'aggregating') return 'client-node active-aggregating'
  return 'client-node'
}

export function TopologySVG() {
  const nodes = useSimulationStore((s) => s.nodes)
  const direction = useSimulationStore((s) => s.packetDirection)
  const dataBySilo = useDataStore((s) => s.dataBySilo)

  const layout = useMemo(() => computeLayout(nodes), [nodes])
  const parentById = useMemo(
    () => new Map(layout.roots.map((r) => [r.node.id, r])),
    [layout.roots],
  )
  // 상위가 꺼져 경로가 끊긴 하위 노드도 흐리게 — 자기 enabled만 보면 참여 중처럼 보인다
  const activeIds = useMemo(
    () => new Set(effectiveEnabledNodes(nodes).map((n) => n.id)),
    [nodes],
  )

  const isTrunkFlowing = direction === 'download' || direction === 'upload'
  const isEdgeFlowing = direction === 'edge-download' || direction === 'edge-upload'

  // 노드가 없으면(목 off 등) 기형 비율의 빈 SVG 대신 안내 문구를 보여준다
  const isEmpty = layout.roots.length === 0

  const [zoom, setZoom] = useState<number>(TOPOLOGY_ZOOM.default)
  /** 화면 이동량(px). transform으로 적용하므로 배율과 무관하게 항상 움직인다 */
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [isPanning, setIsPanning] = useState(false)
  /** 드래그 시작 시점의 포인터 좌표와 이동량 */
  const dragRef = useRef<{ pointerX: number; pointerY: number; panX: number; panY: number } | null>(
    null,
  )

  const applyZoom = (next: number) => {
    // 소수 누적 오차로 min/max에 정확히 안 닿는 걸 막는다
    const clamped = Math.min(
      TOPOLOGY_ZOOM.max,
      Math.max(TOPOLOGY_ZOOM.min, Math.round(next * 10) / 10),
    )
    // 배율은 뷰포트 중앙 기준으로 커지므로, 보고 있던 지점이 중앙에 남으려면
    // 이동량도 같은 비율로 늘려야 한다 (안 그러면 확대할 때마다 위치가 튄다)
    setPan((p) => ({ x: (p.x * clamped) / zoom, y: (p.y * clamped) / zoom }))
    setZoom(clamped)
  }

  const resetView = () => {
    setZoom(TOPOLOGY_ZOOM.default)
    setPan({ x: 0, y: 0 })
  }

  const startPan = (e: React.PointerEvent<HTMLDivElement>) => {
    // 주 버튼 드래그만 팬으로 처리한다 (우클릭·보조 버튼은 통과)
    if (e.button !== 0) return
    e.preventDefault() // 드래그 중 텍스트·SVG 선택 방지
    dragRef.current = { pointerX: e.clientX, pointerY: e.clientY, panX: pan.x, panY: pan.y }
    e.currentTarget.setPointerCapture(e.pointerId)
    setIsPanning(true)
  }

  const movePan = (e: React.PointerEvent<HTMLDivElement>) => {
    const start = dragRef.current
    if (!start) return
    setPan({
      x: start.panX + (e.clientX - start.pointerX),
      y: start.panY + (e.clientY - start.pointerY),
    })
  }

  const endPan = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return
    dragRef.current = null
    e.currentTarget.releasePointerCapture(e.pointerId)
    setIsPanning(false)
  }

  const isMoved = zoom !== TOPOLOGY_ZOOM.default || pan.x !== 0 || pan.y !== 0

  if (isEmpty) {
    return (
      <div className="deploy-empty">
        표시할 연합 네트워크가 없습니다. 목 데이터가 꺼져 있다면 설정에서 활성화하세요.
      </div>
    )
  }

  return (
    <div className="topology-viewport">
      <div className="topology-zoom" role="group" aria-label="토폴로지 화면 배율">
        <button
          type="button"
          className="topology-zoom-btn"
          aria-label="축소"
          title="축소"
          disabled={zoom <= TOPOLOGY_ZOOM.min}
          onClick={() => applyZoom(zoom - TOPOLOGY_ZOOM.step)}
        >
          <i className="fa-solid fa-minus" />
        </button>
        <button
          type="button"
          className={`topology-zoom-level${isMoved ? ' moved' : ''}`}
          aria-label="배율·위치 초기화"
          title="배율·위치 초기화"
          onClick={resetView}
        >
          {Math.round(zoom * 100)}%
        </button>
        <button
          type="button"
          className="topology-zoom-btn"
          aria-label="확대"
          title="확대"
          disabled={zoom >= TOPOLOGY_ZOOM.max}
          onClick={() => applyZoom(zoom + TOPOLOGY_ZOOM.step)}
        >
          <i className="fa-solid fa-plus" />
        </button>
      </div>

      <div
        className={`topology-box${isPanning ? ' panning' : ''}`}
        onPointerDown={startPan}
        onPointerMove={movePan}
        onPointerUp={endPan}
        onPointerCancel={endPan}
      >
        <svg
          className="topology-svg"
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
        >
        <defs>
          <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
          <filter id="small-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* 서버 ↔ 1단 사일로 (WAN) */}
        <g>
          {layout.roots.map((root) => (
            <path
              key={`trunk-${root.node.id}`}
              id={`path-node-${root.node.id}`}
              className={trunkPathClass(direction)}
              d={pathFromSiloToServer(root, layout.server)}
            />
          ))}
        </g>

        {/* 1단 사일로 ↔ 하위 노드 (사내망) */}
        <g>
          {layout.children.map((child) => {
            const parent = parentById.get(child.node.parentId!)
            if (!parent) return null
            return (
              <path
                key={`edge-${child.node.id}`}
                id={`path-edge-${child.node.id}`}
                className={edgePathClass(direction)}
                d={pathFromChildToParent(child, parent)}
              />
            )
          })}
        </g>

        <g>
          {isTrunkFlowing &&
            layout.roots.map((root) => (
              <PacketDot
                key={`packet-${root.node.id}`}
                pathId={`path-node-${root.node.id}`}
                inbound={direction === 'download'}
                color="#06b6d4"
                outboundColor="#a855f7"
              />
            ))}
          {isEdgeFlowing &&
            layout.children.map((child) => (
              <PacketDot
                key={`edge-packet-${child.node.id}`}
                pathId={`path-edge-${child.node.id}`}
                inbound={direction === 'edge-download'}
                color="#06b6d4"
                outboundColor="#a855f7"
              />
            ))}
        </g>

        <g
          className="server-node"
          transform={`translate(${layout.server.x}, ${layout.server.y})`}
        >
          <circle className="node-outer" r={TOPOLOGY.serverRadius} />
          <circle className="node-inner" r={TOPOLOGY.serverRadius - 13} />
          <text className="node-label" y={7} textAnchor="middle">
            <tspan fontFamily="FontAwesome" fontSize={20} fill="#ffffff">
              {''}
            </tspan>
          </text>
          <text className="node-name" y={TOPOLOGY.serverRadius + 24} textAnchor="middle">
            중앙 서버
          </text>
        </g>

        <g>
          {layout.roots.map((root) => (
            <SiloNode
              key={`silo-${root.node.id}`}
              placed={root}
              radius={TOPOLOGY.siloRadius}
              active={activeIds.has(root.node.id)}
              storage={dataBySilo[root.node.id]}
              childCount={layout.children.filter((c) => c.node.parentId === root.node.id).length}
            />
          ))}
        </g>

        <g>
          {layout.children.map((child) => (
            <SiloNode
              key={`child-${child.node.id}`}
              placed={child}
              radius={TOPOLOGY.childRadius}
              active={activeIds.has(child.node.id)}
              storage={dataBySilo[child.node.id]}
              childCount={0}
              isChild
            />
          ))}
          </g>
        </svg>
      </div>
    </div>
  )
}

interface SiloNodeProps {
  placed: PlacedNode
  radius: number
  /** 이번 라운드에 실제로 참여하는지 (자기 enabled + 상위 경로 생존 + 대기 아님) */
  active: boolean
  /** 해당 노드의 저장소 현황. 미등록 노드면 undefined */
  storage?: SiloDataFields
  /** 0보다 크면 로컬 집계자 뱃지를 표시한다 */
  childCount: number
  isChild?: boolean
}

function SiloNode({
  placed,
  radius,
  active,
  storage,
  childCount,
  isChild = false,
}: SiloNodeProps) {
  const { node, x, y } = placed
  const scale = isChild ? TOPOLOGY.storage.childScale : 1
  // 노드명이 원 바로 아래에 오고, 저장소 계층은 그 아래에 붙는다
  const labelY = radius + 19
  const storageTop = labelY + TOPOLOGY.storage.offsetY * scale
  const storageUnits = storage ? deriveStorageUnits(node.id, storage) : []
  return (
    <g
      className={`${clientNodeClass(node.status, active)}${isChild ? ' child-node' : ''}`}
      transform={`translate(${x}, ${y})`}
    >
      <circle className="node-outer" r={radius} />
      <circle className="node-inner" r={radius - 7} />
      <text className="node-label" y={5} textAnchor="middle">
        <tspan fontFamily="FontAwesome" fontSize={isChild ? 10 : 13} fill="#ffffff">
          {isChild ? '' : ''}
        </tspan>
      </text>
      <text className="node-name" y={labelY} textAnchor="middle">
        {node.shortName}
      </text>
      {childCount > 0 && (
        <g className="aggregator-badge" transform={`translate(${radius - 3}, ${-radius + 3})`}>
          <circle r={11} />
          <text y={4.5} textAnchor="middle">
            {childCount}
          </text>
        </g>
      )}
      {storageUnits.length > 0 && (
        <StorageTier
          topY={storageTop}
          linkFromY={labelY + 5}
          scale={scale}
          units={storageUnits}
          nodeName={node.name}
        />
      )}
    </g>
  )
}

interface StorageTierProps {
  /** 노드 중심으로부터 저장소 사각형 윗변까지의 거리 */
  topY: number
  /** 연결선이 뻗어 나오는 지점 (노드명 아래) */
  linkFromY: number
  scale: number
  /** 이 노드에 매달릴 저장소들 */
  units: StorageUnit[]
  nodeName: string
}

/**
 * 노드 아래 저장소 계층을 그린다 — `노드 → 저장소 1~3개 → 각 저장소의 샤드`.
 * 저장소는 사각형(MinIO 인스턴스), 그 아래 작은 칸이 그 저장소가 보유한 샤드다.
 * 채워진 칸이 정제 완료분이라 어느 저장소까지 학습에 쓸 수 있는지 바로 읽힌다.
 * (DB 원통 대신 사각형인 이유: 사일로 저장소는 관계형 DB가 아니라 오브젝트 스토리지다)
 */
function StorageTier({ topY, linkFromY, scale, units, nodeName }: StorageTierProps) {
  const s = TOPOLOGY.storage
  const unitW = s.unitWidth * scale
  const unitH = s.unitHeight * scale
  const unitGap = s.unitGapX * scale
  const shardW = s.shardWidth * scale
  const shardH = s.shardHeight * scale
  const shardGap = s.shardGapX * scale
  const shardTop = topY + unitH + s.shardOffsetY * scale

  const rowWidth = units.length * unitW + (units.length - 1) * unitGap
  const rowLeft = -rowWidth / 2

  return (
    <g className="storage-tier">
      {units.map((unit, i) => {
        const unitLeft = rowLeft + i * (unitW + unitGap)
        const unitCenter = unitLeft + unitW / 2
        const shardsWidth = unit.shardCount * shardW + (unit.shardCount - 1) * shardGap

        return (
          <g key={unit.index} className="storage-unit">
            <title>
              {`${nodeName} 저장소 ${unit.index} · MinIO\n레코드 ${unit.records.toLocaleString()}건 · 샤드 ${unit.shardCount}개 (정제 ${unit.cleansedShards}개)`}
            </title>
            {/* 노드 ↔ 저장소 연결선 — HFL 점선과 구분되도록 가는 실선.
                노드명 글자에 가리지 않게 라벨 아래에서 시작한다. */}
            <line className="storage-link" x1={0} y1={linkFromY} x2={unitCenter} y2={topY} />
            <rect
              className="storage-unit-body"
              x={unitLeft}
              y={topY}
              width={unitW}
              height={unitH}
              rx={2}
            />
            {Array.from({ length: unit.shardCount }, (_, j) => (
              <rect
                key={j}
                className={`shard-cell${j < unit.cleansedShards ? ' cleansed' : ''}`}
                x={unitCenter - shardsWidth / 2 + j * (shardW + shardGap)}
                y={shardTop}
                width={shardW}
                height={shardH}
                rx={0.8}
              />
            ))}
          </g>
        )
      })}
    </g>
  )
}

interface PacketDotProps {
  pathId: string
  /** true면 상위→하위 방향(경로를 역주행), false면 하위→상위 */
  inbound: boolean
  color: string
  outboundColor: string
}

function PacketDot({ pathId, inbound, color, outboundColor }: PacketDotProps) {
  const duration = (1.2 + Math.random() * 0.4).toFixed(2)
  return (
    <circle r={4.5} fill={inbound ? color : outboundColor} filter="url(#small-glow)">
      <animateMotion
        dur={`${duration}s`}
        repeatCount="1"
        fill="freeze"
        calcMode="linear"
        keyPoints={inbound ? '1;0' : '0;1'}
        keyTimes="0;1"
      >
        <mpath href={`#${pathId}`} />
      </animateMotion>
    </circle>
  )
}
