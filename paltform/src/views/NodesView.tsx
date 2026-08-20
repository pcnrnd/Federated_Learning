import { NodeCard } from '@/components/nodes/NodeCard'
import { useSimulationStore } from '@/store/useSimulationStore'

export function NodesView() {
  const nodes = useSimulationStore((s) => s.nodes)

  if (nodes.length === 0) {
    return (
      <div className="tab-pane">
        <div className="deploy-empty">
          표시할 사일로가 없습니다. 목 데이터가 꺼져 있다면 설정에서 활성화하세요.
        </div>
      </div>
    )
  }

  return (
    <div className="tab-pane">
      <div className="nodes-full-grid">
        {nodes.map((node) => (
          <NodeCard key={node.id} node={node} />
        ))}
      </div>
    </div>
  )
}
