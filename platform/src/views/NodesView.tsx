import { NodeCard } from '@/components/nodes/NodeCard'
import { useSimulationStore } from '@/store/useSimulationStore'
import { useSiloStore } from '@/store/useSiloStore'
import { SiloCard } from '@/components/silos/SiloCard'
import { siloActionKey, siloDraftKey } from '@/lib/siloResources'

export function NodesView() {
  const nodes = useSimulationStore((s) => s.nodes)
  const demo = useSimulationStore((s) => s.mockEnabled)
  const silos = useSiloStore((s) => s.silos)
  if (!demo) return <div className="tab-pane">
    <p className="silo-observation">등록 사일로와 실제 자원 관측입니다. 학습 지표·상태는 실제 학습 작업과 분석 화면에서 확인하세요.</p>
    {silos.length ? <div className="silo-grid">{silos.map((silo) => <SiloCard key={siloDraftKey(siloActionKey(silo))} silo={silo} />)}</div>
      : <p className="deploy-empty">서버에서 조회된 사일로가 없습니다. 연결 상태와 등록을 확인하세요.</p>}
  </div>

  if (nodes.length === 0) {
    return (
      <div className="tab-pane">
        <div className="deploy-empty">
          표시할 데모 사일로가 없습니다. 설정에서 데모 데이터를 다시 켜면 예시가 복원됩니다.
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
