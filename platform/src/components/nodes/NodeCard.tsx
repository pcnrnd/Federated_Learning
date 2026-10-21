import { formatNumber, formatPercent } from '@/lib/format'
import type { DisplayNode } from '@/lib/displayNodes'
import { LIVE_NODE_RESTART_REASON, LIVE_NODE_TOGGLE_REASON } from '@/lib/uiMode'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { NodeState } from '@/types/simulation'

const STATUS_CLASS: Record<NodeState['status'], string> = {
  idle: 'status-idle',
  syncing: 'status-syncing',
  training: 'status-training',
  uploading: 'status-uploading',
  aggregating: 'status-aggregating',
}

const STATUS_LABEL: Record<NodeState['status'], string> = {
  idle: 'IDLE',
  syncing: 'SYNCING',
  training: 'TRAINING',
  uploading: 'UPLOADING',
  aggregating: 'AGGREGATING',
}

interface NodeCardProps {
  node: DisplayNode
  interactive?: boolean
  allNodes?: DisplayNode[]
}

export function NodeCard({ node, interactive = true, allNodes }: NodeCardProps) {
  const toggleNode = useSimulationStore((s) => s.toggleNode)
  const restartNode = useSimulationStore((s) => s.restartNode)
  const storeNodes = useSimulationStore((s) => s.nodes)
  const nodes = allNodes ?? storeNodes
  const log = useSimulationStore((s) => s.log)

  const delayClass = node.delay > 70 ? 'text-yellow' : 'text-green'
  const parent = nodes.find((n) => n.id === node.parentId)
  const childCount = nodes.filter((n) => n.parentId === node.id).length
  const roleLabel = parent
    ? `(${parent.name} 하위 노드)`
    : childCount > 0
      ? `(로컬 집계자 · 하위 ${childCount})`
      : '(학습 사일로)'

  const isCutOff = parent !== undefined && !parent.enabled
  const badgeLabel = !node.enabled
    ? 'DISABLED'
    : isCutOff
      ? '상위 비활성'
      : STATUS_LABEL[node.status]
  const badgeClass = !node.enabled || isCutOff ? 'status-disabled' : STATUS_CLASS[node.status]

  const sizeLabel = node.metricUnavailable?.size
    ? '—'
    : `${formatNumber(node.size)} 건 (레코드)`
  const delayLabel = node.metricUnavailable?.delay ? '—' : `${node.delay} ms`
  const accLabel = node.metricUnavailable?.acc ? '—' : formatPercent(node.acc)
  const lossLabel = node.metricUnavailable?.loss ? '—' : node.loss.toFixed(4)
  const cpuLabel = node.metricUnavailable?.cpu ? '—' : `${node.cpu}%`
  const cpuWidth = node.metricUnavailable?.cpu ? 0 : node.cpu

  const handleToggle = () => {
    if (!interactive) return
    toggleNode(node.id)
    log('system', `[${node.name}] ${node.enabled ? '비활성화 — 라운드 참여 제외' : '활성화 — 라운드 참여 재개'}`, node.id)
  }

  const handleRestart = () => {
    if (!interactive) return
    restartNode(node.id)
    log('client', `[${node.name}] 재시작 완료. 로컬 상태를 초기화했습니다.`, node.id)
  }

  return (
    <div className={`glass-panel node-card${node.enabled && !isCutOff ? '' : ' node-disabled'}`}>
      <div className="node-card-header">
        <span className={`node-badge ${badgeClass}`}>{badgeLabel}</span>
        <h3>
          {node.name} <span className="node-card-sub">{roleLabel}</span>
        </h3>
      </div>
      <div className="node-card-body">
        <div className="node-stat-row">
          <span className="label">로컬 데이터</span>
          <span className="val font-semibold">{sizeLabel}</span>
        </div>
        {node.cleanseProgressPct != null && (
          <div className="node-stat-row">
            <span className="label">정제 진행률</span>
            <span className="val text-cyan">{node.cleanseProgressPct}%</span>
          </div>
        )}
        <div className="node-stat-row">
          <span className="label">연결 지연</span>
          <span className={`val ${node.metricUnavailable?.delay ? '' : delayClass}`}>{delayLabel}</span>
        </div>
        <div className="node-stat-row">
          <span className="label">프로세서 부하</span>
          <div className="progress-bar-wrapper">
            <div className="progress-bar" style={{ width: `${cpuWidth}%` }} />
          </div>
          <span className="val progress-text">{cpuLabel}</span>
        </div>
        <div className="node-divider" />
        <div className="node-stat-row font-medium">
          <span className="label">로컬 정확도</span>
          <span className="val text-cyan">{accLabel}</span>
        </div>
        <div className="node-stat-row font-medium">
          <span className="label">로컬 오차율 (Loss)</span>
          <span className="val text-red">{lossLabel}</span>
        </div>
      </div>
      <div className="node-card-footer">
        <div className="class-distribution">
          <span className="label">레이블 데이터 분포 비율 (정상 / 비정상):</span>
          {node.metricUnavailable?.distribution ? (
            <p className="desc">— (미수집)</p>
          ) : (
            <div className="dist-bar">
              <div className="dist-segment seg-1" style={{ width: `${node.normalPct}%` }} />
              <div className="dist-segment seg-2" style={{ width: `${node.abnormalPct}%` }} />
            </div>
          )}
        </div>
        <div className="node-controls">
          <button
            type="button"
            className={`model-action${node.enabled ? '' : ' deploy'}`}
            disabled={!interactive}
            title={interactive ? undefined : LIVE_NODE_TOGGLE_REASON}
            onClick={handleToggle}
          >
            <i className={`fa-solid ${node.enabled ? 'fa-power-off' : 'fa-play'}`} />{' '}
            {node.enabled ? '비활성화' : '활성화'}
          </button>
          <button
            type="button"
            className="model-action"
            disabled={!interactive || !node.enabled}
            title={interactive ? undefined : LIVE_NODE_RESTART_REASON}
            onClick={handleRestart}
          >
            <i className="fa-solid fa-rotate-right" /> 재시작
          </button>
        </div>
      </div>
    </div>
  )
}
