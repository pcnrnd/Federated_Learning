import { useState } from 'react'
import { useSiloStore } from '@/store/useSiloStore'
import type { Silo, SiloThresholds } from '@/types/simulation'
import { exceedsThreshold } from '@/lib/siloResources'

interface SiloCardProps {
  silo: Silo
}

type Metric = keyof SiloThresholds

const METRIC_META: Array<{ key: Metric; label: string }> = [
  { key: 'cpu', label: 'CPU' },
  { key: 'mem', label: '메모리' },
  { key: 'disk', label: '디스크' },
]

function ResourceBar({ label, value, threshold }: { label: string; value: number | null; threshold: number | null }) {
  const over = exceedsThreshold(value, threshold)
  return (
    <div className="silo-metric">
      <div className="silo-metric-head">
        <span className="silo-metric-label">
          {label}
          {over && <i className="fa-solid fa-triangle-exclamation silo-alert-icon" title="임계 초과" />}
        </span>
        <span className={`silo-metric-val${over ? ' text-red' : ''}`}>{value === null ? '미측정' : `${value.toFixed(2)}%`}</span>
      </div>
      <div className="silo-bar-track">
        {value !== null && <div className={`silo-bar-fill${over ? ' over' : ''}`} style={{ width: `${value}%`, minWidth: value > 0 ? 1 : 0 }} />}
        {threshold !== null && <div className="silo-bar-threshold" style={{ left: `${threshold}%` }} title={`임계값 ${threshold}%`} />}
      </div>
    </div>
  )
}

export function SiloCard({ silo }: SiloCardProps) {
  const updateThreshold = useSiloStore((s) => s.updateThreshold)
  const removeSilo = useSiloStore((s) => s.removeSilo)
  const silos = useSiloStore((s) => s.silos)
  const draft = useSiloStore((s) => s.thresholdDrafts[silo.id]) ?? silo.thresholds
  const editThreshold = useSiloStore((s) => s.editThreshold)
  const pending = useSiloStore((s) => s.pending)
  const [editing, setEditing] = useState(false)

  const overCount = METRIC_META.filter((m) => exceedsThreshold(silo[m.key], silo.thresholds[m.key])).length

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
          {/* 1단 사일로(SILO_SEEDS)는 연합 구조의 고정 참여자라 해제 버튼을 노출하지 않는다 */}
          {(!isRoot || silo.serverId) && (
            <button
              type="button"
              className="model-action remove"
              disabled={pending}
              onClick={() => void removeSilo(silo.id)}
            >
              <i className="fa-solid fa-link-slash" /> 해제
            </button>
          )}
        </div>
      </div>

      {silo.serverId && <p className="silo-observation" role="status">
        {silo.serverId} · {({ fresh: '수집 중', stale: '수집 지연', uncollected: '미수집', unsupported: '측정 미지원' } as const)[silo.sampleState ?? 'uncollected']}
        {silo.lastSampleAt && <> · <time dateTime={silo.lastSampleAt}>{new Date(silo.lastSampleAt).toLocaleString()}</time></>}
      </p>}
      {silo.resourceGate && <p className="silo-observation">자원 판정: {({ unknown: '필수 관측 대기', unmonitored: '활성 임계 감시 없음', available: '관측 임계 이내', over_budget: '임계 초과' } as const)[silo.resourceGate]}</p>}
      {(silo.cpuCores != null || silo.memUsedBytes != null) && <p className="silo-observation">
        {silo.cpuCores != null && <>CPU {silo.cpuCores.toFixed(3)} core · </>}
        {silo.memUsedBytes != null && <>메모리 {(silo.memUsedBytes / 1048576).toFixed(1)} MiB</>}
      </p>}

      <div className="silo-endpoint">
        <i className="fa-solid fa-plug" /> <span className="mono">{silo.endpoint}</span>
        <span className="silo-interval">수집주기 {silo.collectIntervalSec}s</span>
        {parentName && <span className="silo-interval">상위 {parentName}</span>}
      </div>

      <div className="silo-metrics">
        {METRIC_META.map((m) => (
          <div key={m.key}>
            <ResourceBar label={m.label} value={silo[m.key]} threshold={silo.thresholds[m.key]} />
            {silo.serverId && <p className="silo-scope">{silo.measurementScope?.[m.key] ?? silo.unavailable?.[m.key] ?? '측정 범위 미확인'}{silo.thresholds[m.key] === null ? ' · 임계 미설정' : silo.capabilities?.[`${m.key}_pct`] === false ? ' · 미지원 임계 감시 비활성' : ''}</p>}
          </div>
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
                value={draft[m.key] ?? ''}
                placeholder="미감시"
                onChange={(e) => editThreshold(silo.id, { [m.key]: e.target.value === '' ? null : Number(e.target.value) })}
              />
            </div>
          ))}
          <button type="button" className="btn btn-primary" disabled={pending} onClick={() => void updateThreshold(silo.id, draft).then((saved) => { if (saved) setEditing(false) })}>임계값 저장</button>
        </div>
      )}
    </div>
  )
}
