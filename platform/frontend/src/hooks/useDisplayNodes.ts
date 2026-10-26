import { useMemo } from 'react'
import { silosToDisplayNodes, type DisplayNode } from '@/lib/displayNodes'
import { resolveUiDataMode } from '@/lib/uiMode'
import { useDataStore } from '@/store/useDataStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import { useSiloStore } from '@/store/useSiloStore'

export interface DisplayNodesResult {
  mode: ReturnType<typeof resolveUiDataMode>
  nodes: DisplayNode[]
  emptyHint: string | null
}

/**
 * 대시보드·노드 화면 공통 노드 목록.
 * 데모는 시뮬레이션 store, 라이브는 등록 사일로 어댑터를 사용한다.
 */
export function useDisplayNodes(): DisplayNodesResult {
  const mockEnabled = useSimulationStore((s) => s.mockEnabled)
  const simulationNodes = useSimulationStore((s) => s.nodes)
  const silos = useSiloStore((s) => s.silos)
  const dataBySilo = useDataStore((s) => s.dataBySilo)
  const mode = resolveUiDataMode(mockEnabled)

  return useMemo(() => {
    if (mode === 'demo') {
      return {
        mode,
        nodes: simulationNodes,
        emptyHint:
          simulationNodes.length === 0
            ? '표시할 사일로가 없습니다. 사일로를 등록하면 여기에 표시됩니다.'
            : null,
      }
    }
    const nodes = silosToDisplayNodes(silos, dataBySilo)
    return {
      mode,
      nodes,
      emptyHint:
        nodes.length === 0
          ? '서버에서 조회된 사일로가 없습니다. 연결 상태와 등록을 확인하세요.'
          : null,
    }
  }, [mode, simulationNodes, silos, dataBySilo])
}
