import { TAB_META } from '@/constants/simulation'
import { formatMB, formatPercent } from '@/lib/format'
import { useSimulationStore } from '@/store/useSimulationStore'

export function GlobalHeader() {
  const activeTab = useSimulationStore((s) => s.activeTab)
  const currentRound = useSimulationStore((s) => s.currentRound)
  const totalRounds = useSimulationStore((s) => s.config.totalRounds)
  const accuracy = useSimulationStore((s) => s.global.accuracy)
  const traffic = useSimulationStore((s) => s.global.accumulatedTraffic)
  const mockEnabled = useSimulationStore((s) => s.mockEnabled)
  const points = useSimulationStore((s) => s.chartPoints)
  const actualAccuracy = points[points.length - 1]?.accuracy
  const meta = TAB_META[activeTab]

  return (
    <header className="global-header glass-panel">
      <div className="page-title-area">
        <h1>
          {meta.title}
          {mockEnabled && (
            <span className="model-badge model-badge-experimental" title="설정에서 데모 데이터 시뮬레이션이 켜져 있습니다">
              데모 데이터 모드
            </span>
          )}
        </h1>
        <p>{meta.desc}</p>
      </div>
      <div className="header-right">
        <div className="header-metrics">
          <div className="header-metric-card">
            <span className="lbl">{mockEnabled ? '현재 라운드' : '기록된 라운드'}</span>
            <span className="val">
              {mockEnabled ? `${currentRound} / ${totalRounds}` : currentRound}
            </span>
          </div>
          <div className="header-metric-card">
            <span className="lbl">글로벌 정확도</span>
            <span className="val text-cyan">{mockEnabled ? formatPercent(accuracy) : actualAccuracy === undefined ? '미수집' : formatPercent(actualAccuracy)}</span>
          </div>
          <div className="header-metric-card">
            <span className="lbl">누적 전송 트래픽</span>
            <span className="val text-purple">{mockEnabled ? formatMB(traffic) : '미수집'}</span>
          </div>
        </div>
      </div>
    </header>
  )
}
