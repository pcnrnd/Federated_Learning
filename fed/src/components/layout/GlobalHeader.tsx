import { TAB_META } from '@/constants/simulation'
import { formatMB, formatPercent } from '@/lib/format'
import { useSimulationStore } from '@/store/useSimulationStore'
import { ThemeToggle } from './ThemeToggle'

export function GlobalHeader() {
  const activeTab = useSimulationStore((s) => s.activeTab)
  const currentRound = useSimulationStore((s) => s.currentRound)
  const totalRounds = useSimulationStore((s) => s.config.totalRounds)
  const accuracy = useSimulationStore((s) => s.global.accuracy)
  const traffic = useSimulationStore((s) => s.global.accumulatedTraffic)
  const meta = TAB_META[activeTab]

  return (
    <header className="global-header glass-panel">
      <div className="page-title-area">
        <h1>{meta.title}</h1>
        <p>{meta.desc}</p>
      </div>
      <div className="header-right">
        <div className="header-metrics">
          <div className="header-metric-card">
            <span className="lbl">현재 라운드</span>
            <span className="val">
              {currentRound} / {totalRounds}
            </span>
          </div>
          <div className="header-metric-card">
            <span className="lbl">글로벌 정확도</span>
            <span className="val text-cyan">{formatPercent(accuracy)}</span>
          </div>
          <div className="header-metric-card">
            <span className="lbl">누적 전송 트래픽</span>
            <span className="val text-purple">{formatMB(traffic)}</span>
          </div>
        </div>
        <ThemeToggle />
      </div>
    </header>
  )
}
