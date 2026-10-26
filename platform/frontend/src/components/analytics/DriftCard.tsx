import { useEffect } from 'react'
import { isLiveConfigured } from '@/api/client'
import { useDriftDisplay } from '@/hooks/useDriftDisplay'
import { resolveUiDataMode } from '@/lib/uiMode'
import { useModelStore } from '@/store/useModelStore'
import { useMonitoringStore } from '@/store/useMonitoringStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import { LiveDriftCard } from './LiveDrift'

const LEVEL_META = {
  ok: { label: '정상', icon: 'fa-circle-check' },
  warn: { label: '주의', icon: 'fa-triangle-exclamation' },
  alert: { label: '임계 초과', icon: 'fa-circle-exclamation' },
} as const

export function DriftCard() {
  const mockEnabled = useSimulationStore((state) => state.mockEnabled)
  const mode = resolveUiDataMode(mockEnabled)
  const display = useDriftDisplay()
  const triggerRetrain = useModelStore((s) => s.triggerRetrain)
  const observe = useMonitoringStore((s) => s.observeLive)

  useEffect(() => {
    if (mode === 'live') return observe()
  }, [mode, observe])

  const meta = LEVEL_META[display.level]

  return (
    <>
      <div className={`drift-card glass-panel drift-${display.level}`}>
        <div className="drift-left">
          <span className="drift-title">
            <i className="fa-solid fa-wave-square" /> 데이터 드리프트
          </span>
          <span className={`drift-badge drift-badge-${display.level}`}>
            <i className={`fa-solid ${meta.icon}`} /> {meta.label}
          </span>
        </div>
        <div className="drift-center">
          <div className="drift-metric-row">
            <span className={`drift-score drift-score-${display.level}`}>{display.scoreText}</span>
            <div className="drift-track">
              <div
                className={`drift-fill drift-fill-${display.level}`}
                style={{ width: `${display.fillPercent}%` }}
              />
              <div
                className="drift-threshold"
                style={{ left: `${display.alertThresholdLine}%` }}
                title="경보 임계"
              />
            </div>
          </div>
          <p className="drift-desc">
            {display.description}
            {mode === 'demo' && ` (라운드 ${display.roundLabel})`}
            {mode === 'live' && display.roundLabel !== '—' && ` · ${display.roundLabel}`}
          </p>
        </div>
        <div className="drift-actions">
          {display.showRetrain && (
            <button
              type="button"
              className="btn btn-secondary drift-retrain-btn"
              disabled={display.retrainDisabled}
              title={display.retrainTitle}
              onClick={() => {
                if (!display.retrainDisabled) triggerRetrain()
              }}
            >
              <i className="fa-solid fa-arrows-rotate" /> 재학습 트리거
            </button>
          )}
        </div>
      </div>
      {mode === 'live' && isLiveConfigured() && <LiveDriftCard compact />}
    </>
  )
}
