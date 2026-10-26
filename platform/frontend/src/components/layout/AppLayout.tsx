import type { ReactNode } from 'react'
import { GlobalHeader } from './GlobalHeader'
import { Sidebar } from './Sidebar'
import { DataSourceStatus } from './DataSourceStatus'

interface AppLayoutProps {
  children: ReactNode
}

export function AppLayout({ children }: AppLayoutProps) {
  return (
    <>
      <div className="glass-bg" />
      <div className="glow-orb orb-1" />
      <div className="glow-orb orb-2" />
      <div className="app-layout">
        <Sidebar />
        <main className="main-viewport">
          <GlobalHeader />
          <div className="content-viewport-container"><DataSourceStatus />{children}</div>
        </main>
      </div>
    </>
  )
}
