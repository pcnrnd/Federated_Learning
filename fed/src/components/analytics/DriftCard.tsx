import { MONITOR_PREVIEW_POINTS } from '@/constants/simulation'
import { useModelStore } from '@/store/useModelStore'
import { useMonitoringStore } from '@/store/useMonitoringStore'
import { useSimulationStore } from '@/store/useSimulationStore'

type DriftLevel = 'ok' | 'warn' | 'alert'

/** 드리프트 점수와 스토어 임계치(%)에 따른 경보 수준을 반환한다. */
function driftLevel(drift: number, warnPct: number, alertPct: number): DriftLevel {
  const warn = warnPct / 100
  const alert = alertPct / 100
  if (drift >= alert) return 'alert'
  if (drift >= warn) return 'warn'
  return 'ok'
}

const LEVEL_META: Record<DriftLevel, { label: string; icon: string }> = {
  ok: { label: '정상', icon: 'fa-circle-check' },
  warn: { label: '주의', icon: 'fa-triangle-exclamation' },
  alert: { label: '임계 초과', icon: 'fa-circle-exclamation' },
}

export function DriftCard() {
  const monitorPoints = useSimulationStore((s) => s.monitorPoints)
  const triggerRetrain = useModelStore((s) => s.triggerRetrain)
  const warnThreshold = useMonitoringStore((s) => s.warnThreshold)
  const alertThreshold = useMonitoringStore((s) => s.alertThreshold)

  const latest =
    monitorPoints.length > 0
      ? monitorPoints[monitorPoints.length - 1]
      : MONITOR_PREVIEW_POINTS[MONITOR_PREVIEW_POINTS.length - 1]

  const level = driftLevel(latest.drift, warnThreshold, alertThreshold)
  const meta = LEVEL_META[level]
  const pct = (latest.drift * 100).toFixed(1)

  return (
    <div className={`drift-card glass-panel drift-${level}`}>
      <div className="drift-left">
        <span className="drift-title">
          <i className="fa-solid fa-wave-square" /> 데이터 드리프트
        </span>
        <span className={`drift-badge drift-badge-${level}`}>
          <i className={`fa-solid ${meta.icon}`} /> {meta.label}
        </span>
      </div>

      <div className="drift-center">
        <div className="drift-metric-row">
          <span className={`drift-score drift-score-${level}`}>{pct}%</span>
          <div className="drift-track">
            <div
              className={`drift-fill drift-fill-${level}`}
              style={{ width: `${Math.min(100, latest.drift * 100)}%` }}
            />
            <div
              className="drift-threshold"
              style={{ left: `${alertThreshold}%` }}
              title="경보 임계"
            />
          </div>
        </div>
        <p className="drift-desc">
          기준 분포 대비 변화 점수 (라운드 {latest.round})
          {level === 'alert' && ' — 재학습 검토 필요'}
        </p>
      </div>

      <div className="drift-actions">
        {level !== 'ok' && (
          <button type="button" className="btn btn-secondary drift-retrain-btn" onClick={() => triggerRetrain()}>
            <i className="fa-solid fa-arrows-rotate" /> 재학습 트리거
          </button>
        )}
      </div>
    </div>
  )
}
