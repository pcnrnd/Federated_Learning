import { AppLayout } from '@/components/layout/AppLayout'
import { useSimulationStore } from '@/store/useSimulationStore'
import { AnalyticsView } from '@/views/AnalyticsView'
import { DashboardView } from '@/views/DashboardView'
import { LogsView } from '@/views/LogsView'
import { NodesView } from '@/views/NodesView'
import type { TabId } from '@/types/simulation'
import type { ReactNode } from 'react'

const VIEW_REGISTRY: Record<TabId, ReactNode> = {
  dashboard: <DashboardView />,
  nodes: <NodesView />,
  analytics: <AnalyticsView />,
  logs: <LogsView />,
}

export default function App() {
  const activeTab = useSimulationStore((s) => s.activeTab)
  return <AppLayout>{VIEW_REGISTRY[activeTab]}</AppLayout>
}
