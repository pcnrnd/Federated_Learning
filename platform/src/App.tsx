import { useEffect } from 'react'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { AppLayout } from '@/components/layout/AppLayout'
import { useLivePolling } from '@/hooks/useLivePolling'
import { SimulationEngineHost } from '@/hooks/useSimulationEngine'
import { useSystemHeartbeat } from '@/hooks/useSystemHeartbeat'
import { clearAllMockData } from '@/lib/mockData'
import { useSimulationStore } from '@/store/useSimulationStore'
import { AnalyticsView } from '@/views/AnalyticsView'
import { DashboardView } from '@/views/DashboardView'
import { DataView } from '@/views/DataView'
import { LogsView } from '@/views/LogsView'
import { ModelsView } from '@/views/ModelsView'
import { NodesView } from '@/views/NodesView'
import { SilosView } from '@/views/SilosView'
import type { TabId } from '@/types/simulation'
import type { ReactNode } from 'react'

const VIEW_REGISTRY: Record<TabId, ReactNode> = {
  dashboard: <DashboardView />,
  nodes: <NodesView />,
  silos: <SilosView />,
  data: <DataView />,
  models: <ModelsView />,
  analytics: <AnalyticsView />,
  logs: <LogsView />,
}

export default function App() {
  const activeTab = useSimulationStore((s) => s.activeTab)
  useSystemHeartbeat()
  useLivePolling()

  // 스토어는 항상 시드로 초기화되므로, 목 off가 저장된 채 새로고침하면 여기서 비운다
  useEffect(() => {
    if (!useSimulationStore.getState().mockEnabled) clearAllMockData()
  }, [])

  return (
    <>
      <SimulationEngineHost />
      <AppLayout>
        <ErrorBoundary resetKey={activeTab}>{VIEW_REGISTRY[activeTab]}</ErrorBoundary>
      </AppLayout>
    </>
  )
}
