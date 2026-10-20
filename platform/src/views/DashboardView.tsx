import { ControlPanel } from '@/components/controls/ControlPanel'
import { TopologySVG } from '@/components/topology/TopologySVG'
import { RegisteredNetwork } from '@/components/topology/RegisteredNetwork'
import { useSimulationStore } from '@/store/useSimulationStore'

export function DashboardView() {
  const demo = useSimulationStore((s) => s.mockEnabled)
  return (
    <div className="tab-pane">
      <div className="dashboard-split-grid">
        <ControlPanel />
        <div className="glass-panel content-card">
          <div className="card-header">
            <h3>
              <i className="fa-solid fa-circle-nodes" /> 실시간 연합 네트워크
            </h3>
            <span className="desc">Encrypted Data Channels & Flow Visualizer</span>
          </div>
          <div className="card-body flex-center">
            {demo ? <TopologySVG /> : <RegisteredNetwork />}
          </div>
        </div>
      </div>
    </div>
  )
}
