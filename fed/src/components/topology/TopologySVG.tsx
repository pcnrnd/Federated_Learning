import { TOPOLOGY } from '@/constants/simulation'
import { getNodeCoords, pathFromNodeToCenter } from '@/lib/topology'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { NodeStatus, PacketDirection } from '@/types/simulation'

function pathClass(direction: PacketDirection): string {
  if (direction === 'download') return 'network-path active-download'
  if (direction === 'upload') return 'network-path active-upload'
  return 'network-path'
}

function clientNodeClass(status: NodeStatus): string {
  if (status === 'syncing') return 'client-node active-sync'
  if (status === 'training') return 'client-node active-local'
  if (status === 'uploading') return 'client-node active-upload'
  return 'client-node'
}

export function TopologySVG() {
  const nodes = useSimulationStore((s) => s.nodes)
  const direction = useSimulationStore((s) => s.packetDirection)

  return (
    <div className="topology-box">
      <svg
        className="topology-svg"
        viewBox={`0 0 ${TOPOLOGY.viewBox.width} ${TOPOLOGY.viewBox.height}`}
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

        <g>
          {nodes.map((node) => (
            <path
              key={`path-${node.id}`}
              id={`path-node-${node.id}`}
              className={pathClass(direction)}
              d={pathFromNodeToCenter(node.id)}
            />
          ))}
        </g>

        <g>
          {(direction === 'download' || direction === 'upload') &&
            nodes.map((node) => (
              <PacketDot key={`packet-${node.id}`} nodeId={node.id} direction={direction} />
            ))}
        </g>

        <g
          className="server-node"
          transform={`translate(${TOPOLOGY.centerX}, ${TOPOLOGY.centerY})`}
        >
          <circle className="node-outer" r={32} />
          <circle className="node-inner" r={22} />
          <text className="node-label" y={4} textAnchor="middle">
            <tspan fontFamily="FontAwesome" fontSize={14} fill="#ffffff">
              {''}
            </tspan>
          </text>
          <text className="node-name" y={48} textAnchor="middle">
            중앙 서버
          </text>
        </g>

        <g>
          {nodes.map((node) => {
            const { x, y } = getNodeCoords(node.id)
            return (
              <g
                key={`client-${node.id}`}
                className={clientNodeClass(node.status)}
                transform={`translate(${x}, ${y})`}
              >
                <circle className="node-outer" r={16} />
                <circle className="node-inner" r={11} />
                <text className="node-label" y={3} textAnchor="middle">
                  <tspan fontFamily="FontAwesome" fontSize={8} fill="#ffffff">
                    {''}
                  </tspan>
                </text>
                <text className="node-name" y={26} textAnchor="middle">
                  {node.name}
                </text>
              </g>
            )
          })}
        </g>
      </svg>
    </div>
  )
}

interface PacketDotProps {
  nodeId: number
  direction: 'download' | 'upload'
}

function PacketDot({ nodeId, direction }: PacketDotProps) {
  const color = direction === 'download' ? '#06b6d4' : '#a855f7'
  const duration = (1.2 + Math.random() * 0.4).toFixed(2)
  const isDownload = direction === 'download'
  return (
    <circle r={4} fill={color} filter="url(#small-glow)">
      <animateMotion
        dur={`${duration}s`}
        repeatCount="1"
        fill="freeze"
        calcMode="linear"
        keyPoints={isDownload ? '1;0' : '0;1'}
        keyTimes="0;1"
      >
        <mpath href={`#path-node-${nodeId}`} />
      </animateMotion>
    </circle>
  )
}
