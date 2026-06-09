import { useState } from 'react'
import { useSiloStore } from '@/store/useSiloStore'
import type { Silo, SiloThresholds } from '@/types/simulation'

interface SiloCardProps {
  silo: Silo
}

type Metric = keyof SiloThresholds

const METRIC_META: Array<{ key: Metric; label: string }> = [
  { key: 'cpu', label: 'CPU' },
  { key: 'mem', label: '메모리' },
  { key: 'disk', label: '디스크' },
]

function ResourceBar({ label, value, threshold }: { label: string; value: number; threshold: number }) {
  const over = value >= threshold
  return (
    <div className="silo-metric">
      <div className="silo-metric-head">
        <span className="silo-metric-label">
          {label}
          {over && <i className="fa-solid fa-triangle-exclamation silo-alert-icon" title="임계 초과" />}
        </span>
        <span className={`silo-metric-val${over ? ' text-red' : ''}`}>{value}%</span>
      </div>
      <div className="silo-bar-track">
        <div className={`silo-bar-fill${over ? ' over' : ''}`} style={{ width: `${value}%` }} />
        <div className="silo-bar-threshold" style={{ left: `${threshold}%` }} title={`임계값 ${threshold}%`} />
      </div>
    </div>
  )
}

export function SiloCard({ silo }: SiloCardProps) {
  const updateThreshold = useSiloStore((s) => s.updateThreshold)
  const removeSilo = useSiloStore((s) => s.removeSilo)
  const [editing, setEditing] = useState(false)

  const overCount = METRIC_META.filter((m) => silo[m.key] >= silo.thresholds[m.key]).length

  return (
    <div className="glass-panel silo-card">
      <div className="silo-card-head">
        <div className="silo-title">
          <span className={`silo-status-dot${overCount > 0 ? ' alert' : ''}`} />
          <h3>{silo.name}</h3>
        </div>
        <div className="silo-card-actions">
          <button
            type="button"
            className="model-action"
            onClick={() => setEditing((v) => !v)}
            title="임계값 설정"
          >
            <i className="fa-solid fa-sliders" /> 임계값
          </button>
          <button type="button" className="model-action remove" onClick={() => removeSilo(silo.id)}>
            <i className="fa-solid fa-link-slash" /> 해제
          </button>
        </div>
      </div>

      <div className="silo-endpoint">
        <i className="fa-solid fa-plug" /> <span className="mono">{silo.endpoint}</span>
        <span className="silo-interval">수집주기 {silo.collectIntervalSec}s</span>
      </div>

      <div className="silo-metrics">
        {METRIC_META.map((m) => (
          <ResourceBar key={m.key} label={m.label} value={silo[m.key]} threshold={silo.thresholds[m.key]} />
        ))}
      </div>

      {editing && (
        <div className="silo-threshold-editor">
          {METRIC_META.map((m) => (
            <div key={m.key} className="control-group">
              <label htmlFor={`th-${silo.id}-${m.key}`}>{m.label} 임계(%)</label>
              <input
                id={`th-${silo.id}-${m.key}`}
                type="number"
                className="model-input"
                min={0}
                max={100}
                value={silo.thresholds[m.key]}
                onChange={(e) => updateThreshold(silo.id, { [m.key]: Number(e.target.value) })}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
