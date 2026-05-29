import { PerformanceChart } from '@/components/analytics/PerformanceChart'

export function AnalyticsView() {
  return (
    <div className="tab-pane">
      <div className="glass-panel content-card full-card">
        <div className="card-header">
          <h3>
            <i className="fa-solid fa-chart-line" /> 정확도 향상 및 손실 수렴 추이 곡선
            (Global Metrics)
          </h3>
          <span className="desc">
            Interactive charts monitoring loss reduction and model optimization across training rounds.
          </span>
        </div>
        <div className="card-body">
          <PerformanceChart />
        </div>
      </div>
    </div>
  )
}
