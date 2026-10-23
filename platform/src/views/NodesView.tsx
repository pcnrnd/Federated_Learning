import { NodeCard } from '@/components/nodes/NodeCard'
import { useDisplayNodes } from '@/hooks/useDisplayNodes'

export function NodesView() {
  const { mode, nodes, emptyHint } = useDisplayNodes()

  if (emptyHint) {
    return (
      <div className="tab-pane">
        <div className="deploy-empty">{emptyHint}</div>
      </div>
    )
  }

  return (
    <div className="tab-pane">
      {mode !== 'demo' && (
        <p className="silo-observation">
          등록 사일로와 실제 자원·정제 관측입니다. 학습 지표·상태는 실제 학습 작업과 분석 화면에서 확인하세요.
        </p>
      )}
      <div className="nodes-full-grid">
        {nodes.map((node) => (
          <NodeCard
            key={node.id}
            node={node}
            interactive={mode === 'demo'}
            allNodes={mode === 'demo' ? undefined : nodes}
          />
        ))}
      </div>
    </div>
  )
}
