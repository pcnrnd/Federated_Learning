import { DriftCard } from '@/components/analytics/DriftCard'
import { DriftSettingsPanel } from '@/components/analytics/DriftSettingsPanel'
import { MonitorChart } from '@/components/analytics/MonitorChart'
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

      <div className="glass-panel content-card full-card">
        <div className="card-header">
          <h3>
            <i className="fa-solid fa-gauge-high" /> 모델 운영 모니터링 (처리량 · 처리시간 · 드리프트)
          </h3>
          <span className="desc">
            Operational KPIs — throughput, latency &amp; data drift detection.
          </span>
        </div>
        <div className="card-body">
          <div className="monitor-layout">
            <div className="monitor-drift-section">
              <DriftCard />
              <DriftSettingsPanel />
            </div>
            <MonitorChart />
          </div>
        </div>
      </div>
    </div>
  )
}
