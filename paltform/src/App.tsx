import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { AppLayout } from '@/components/layout/AppLayout'
import { SimulationEngineHost } from '@/hooks/useSimulationEngine'
import { useSystemHeartbeat } from '@/hooks/useSystemHeartbeat'
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

  return (
    <>
      <SimulationEngineHost />
      <AppLayout>
        <ErrorBoundary resetKey={activeTab}>{VIEW_REGISTRY[activeTab]}</ErrorBoundary>
      </AppLayout>
    </>
  )
}
