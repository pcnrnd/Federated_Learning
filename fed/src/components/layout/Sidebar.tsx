import { TAB_META } from '@/constants/simulation'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { TabId } from '@/types/simulation'

const TAB_ORDER: TabId[] = [
  'dashboard',
  'nodes',
  'silos',
  'data',
  'models',
  'analytics',
  'logs',
]

export function Sidebar() {
  const activeTab = useSimulationStore((s) => s.activeTab)
  const setActiveTab = useSimulationStore((s) => s.setActiveTab)

  return (
    <aside className="sidebar glass-panel">
      <div className="sidebar-header">
        <div className="logo-wrapper">
          <i className="fa-solid fa-network-wired logo-icon" />
        </div>
        <div className="logo-title">
          <h2>FEDERATED</h2>
          <span>COORDINATOR</span>
        </div>
      </div>

      <nav className="sidebar-menu">
        {TAB_ORDER.map((id) => {
          const meta = TAB_META[id]
          const isActive = activeTab === id
          return (
            <button
              key={id}
              type="button"
              className={`menu-btn${isActive ? ' active' : ''}`}
              onClick={() => setActiveTab(id)}
            >
              <i className={`fa-solid ${meta.icon}`} /> {meta.title}
            </button>
          )
        })}
      </nav>

      <div className="sidebar-footer">
        <div className="user-profile">
          <div className="user-avatar">
            <i className="fa-solid fa-user-shield" />
          </div>
          <div className="user-info">
            <span className="user-name">관리자</span>
            <span className="user-role">System Administrator</span>
          </div>
        </div>
        <div className="sidebar-status">
          <span className="status-pulse" />
          <span className="status-lbl">ORCHESTRATOR ACTIVE</span>
        </div>
      </div>
    </aside>
  )
}
