import { NodeCard } from '@/components/nodes/NodeCard'
import { useSimulationStore } from '@/store/useSimulationStore'

export function NodesView() {
  const nodes = useSimulationStore((s) => s.nodes)
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
