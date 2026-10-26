import { useMemo } from 'react'
import { LiveTopology } from '@/components/visualization/LiveTopology'
import { registeredTopology } from '@/lib/registeredTopology'
import { layoutVizTopology } from '@/lib/vizTopology'
import { useSiloStore } from '@/store/useSiloStore'

export function RegisteredNetwork() {
  const silos = useSiloStore((s) => s.silos)
  const layout = useMemo(() => layoutVizTopology(registeredTopology(silos)), [silos])
  return layout.nodes.length ? <LiveTopology layout={layout} />
    : <p className="deploy-empty">서버에서 조회된 등록 사일로가 없습니다. 연결 상태와 사일로 등록을 확인하세요.</p>
}
