import type { ReactNode } from 'react'

interface AnalyticsChartFrameProps {
  children: ReactNode
  overlayMessage?: string | null
}

export function AnalyticsChartFrame({ children, overlayMessage }: AnalyticsChartFrameProps) {
  return (
    <div className="analytics-chart-box">
      {children}
      {overlayMessage && (
        <div className="analytics-chart-overlay" role="status">
          <p className="deploy-empty">{overlayMessage}</p>
        </div>
      )}
    </div>
  )
}
