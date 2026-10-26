import { useMemo } from 'react'
import { MONITOR_PREVIEW_POINTS } from '@/constants/simulation'
import { driftScopeKey } from '@/lib/distributionDrift'
import { resolveUiDataMode } from '@/lib/uiMode'
import { useMonitoringStore } from '@/store/useMonitoringStore'
import { useSimulationStore } from '@/store/useSimulationStore'

export type DriftLevel = 'ok' | 'warn' | 'alert'

export interface DriftDisplay {
  level: DriftLevel
  scoreText: string
  fillPercent: number
  description: string
  roundLabel: string
  showRetrain: boolean
  retrainDisabled: boolean
  retrainTitle?: string
  alertThresholdLine: number
}

function driftLevelFromPct(drift: number, warnPct: number, alertPct: number): DriftLevel {
  const warn = warnPct / 100
  const alert = alertPct / 100
  if (drift >= alert) return 'alert'
  if (drift >= warn) return 'warn'
  return 'ok'
}

export function useDriftDisplay(): DriftDisplay {
  const mockEnabled = useSimulationStore((s) => s.mockEnabled)
  const monitorPoints = useSimulationStore((s) => s.monitorPoints)
  const warnThreshold = useMonitoringStore((s) => s.warnThreshold)
  const alertThreshold = useMonitoringStore((s) => s.alertThreshold)
  const liveRows = useMonitoringStore((s) => s.liveRows)
  const selectedScope = useMonitoringStore((s) => s.selectedScope)
  const mode = resolveUiDataMode(mockEnabled)

  return useMemo(() => {
    if (mode === 'demo') {
      const latest =
        monitorPoints.length > 0
          ? monitorPoints[monitorPoints.length - 1]
          : MONITOR_PREVIEW_POINTS[MONITOR_PREVIEW_POINTS.length - 1]
      const level = driftLevelFromPct(latest.drift, warnThreshold, alertThreshold)
      const pct = latest.drift * 100
      return {
        level,
        scoreText: `${pct.toFixed(1)}%`,
        fillPercent: Math.min(100, pct),
        roundLabel: String(latest.round),
        description: `기준 분포 대비 변화 점수 (라운드 ${latest.round})${
          level === 'alert' ? ' — 재학습 검토 필요' : ''
        }`,
        showRetrain: level !== 'ok',
        retrainDisabled: false,
        alertThresholdLine: alertThreshold,
      }
    }

    const row = liveRows.find((value) => driftScopeKey(value) === selectedScope) ?? liveRows[0]
    if (!row) {
      return {
        level: 'warn',
        scoreText: '—',
        fillPercent: 0,
        roundLabel: '—',
        description: '수집 설정 또는 실제 관측이 없습니다.',
        showRetrain: false,
        retrainDisabled: true,
        alertThresholdLine: 100,
      }
    }

    const critical = row.policy?.critical_threshold ?? 0.25
    const level: DriftLevel =
      row.state === 'ready' && row.severity
        ? row.severity === 'critical'
          ? 'alert'
          : row.severity === 'warning'
            ? 'warn'
            : 'ok'
        : 'warn'
    const psiText = row.psi === null ? '—' : row.psi.toFixed(4)
    const fill =
      row.psi === null ? 0 : Math.min(100, (row.psi / Math.max(critical, 0.001)) * 100)

    return {
      level,
      scoreText: row.psi === null ? '—' : `PSI ${psiText}`,
      fillPercent: fill,
      roundLabel: row.node_id,
      description: row.reason || `${row.model_name}@${row.version} · ${row.feature}`,
      showRetrain: level !== 'ok',
      retrainDisabled: true,
      alertThresholdLine: Math.min(100, critical * 100),
    }
  }, [mode, monitorPoints, warnThreshold, alertThreshold, liveRows, selectedScope])
}
