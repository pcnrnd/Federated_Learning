import { formatNumber, formatPercent } from '@/lib/format'
import type { NodeState } from '@/types/simulation'

const STATUS_CLASS: Record<NodeState['status'], string> = {
  idle: 'status-idle',
  syncing: 'status-syncing',
  training: 'status-training',
  uploading: 'status-uploading',
}

const STATUS_LABEL: Record<NodeState['status'], string> = {
  idle: 'IDLE',
  syncing: 'SYNCING',
  training: 'TRAINING',
  uploading: 'UPLOADING',
}

interface NodeCardProps {
  node: NodeState
}

export function NodeCard({ node }: NodeCardProps) {
  const delayClass = node.delay > 70 ? 'text-yellow' : 'text-green'

  return (
    <div className="glass-panel node-card">
      <div className="node-card-header">
        <span className={`node-badge ${STATUS_CLASS[node.status]}`}>
          {STATUS_LABEL[node.status]}
        </span>
        <h3>
          노드 {node.id} (분산 데이터 노드)
        </h3>
      </div>
      <div className="node-card-body">
        <div className="node-stat-row">
          <span className="label">로컬 데이터</span>
          <span className="val font-semibold">{formatNumber(node.size)} 건 (레코드)</span>
        </div>
        <div className="node-stat-row">
          <span className="label">연결 지연</span>
          <span className={`val ${delayClass}`}>{node.delay} ms</span>
        </div>
        <div className="node-stat-row">
          <span className="label">프로세서 부하</span>
          <div className="progress-bar-wrapper">
            <div className="progress-bar" style={{ width: `${node.cpu}%` }} />
          </div>
          <span className="val progress-text">{node.cpu}%</span>
        </div>
        <div className="node-divider" />
        <div className="node-stat-row font-medium">
          <span className="label">로컬 정확도</span>
          <span className="val text-cyan">{formatPercent(node.acc)}</span>
        </div>
        <div className="node-stat-row font-medium">
          <span className="label">로컬 오차율 (Loss)</span>
          <span className="val text-red">{node.loss.toFixed(4)}</span>
        </div>
      </div>
      <div className="node-card-footer">
        <div className="class-distribution">
          <span className="label">
            레이블 데이터 분포 비율 (정상 / 비정상):
          </span>
          <div className="dist-bar">
            <div
              className="dist-segment seg-1"
              style={{ width: `${node.normalPct}%` }}
              title={`정상 비율: ${node.normalPct}%`}
            />
            <div
              className="dist-segment seg-2"
              style={{ width: `${node.abnormalPct}%` }}
              title={`비정상 비율: ${node.abnormalPct}%`}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
