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
  const silos = useSiloStore((s) => s.silos)
  const [editing, setEditing] = useState(false)

  const overCount = METRIC_META.filter((m) => silo[m.key] >= silo.thresholds[m.key]).length

  const isRoot = silo.parentId === undefined
  const parentName = isRoot ? null : silos.find((s) => s.id === silo.parentId)?.name
  const childCount = silos.filter((s) => s.parentId === silo.id).length

  return (
    <div className="glass-panel silo-card">
      <div className="silo-card-head">
        <div className="silo-title">
          <span className={`silo-status-dot${overCount > 0 ? ' alert' : ''}`} />
          <h3>{silo.name}</h3>
          {childCount > 0 && (
            <span className="silo-tier-badge" title="하위 노드의 로컬 집계를 담당합니다">
              <i className="fa-solid fa-sitemap" /> 로컬 집계자 {childCount}
            </span>
          )}
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
          {/* 1단 사일로 12개는 연합 구조의 고정 참여자라 해제 버튼을 노출하지 않는다 */}
          {!isRoot && (
            <button
              type="button"
              className="model-action remove"
              onClick={() => removeSilo(silo.id)}
            >
              <i className="fa-solid fa-link-slash" /> 해제
            </button>
          )}
        </div>
      </div>

      <div className="silo-endpoint">
        <i className="fa-solid fa-plug" /> <span className="mono">{silo.endpoint}</span>
        <span className="silo-interval">수집주기 {silo.collectIntervalSec}s</span>
        {parentName && <span className="silo-interval">상위 {parentName}</span>}
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
