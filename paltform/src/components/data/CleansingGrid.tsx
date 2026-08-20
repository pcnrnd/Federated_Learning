import { formatNumber } from '@/lib/format'
import { useDataStore } from '@/store/useDataStore'
import type { SiloData } from '@/types/simulation'

interface CleansingGridProps {
  siloData: SiloData[]
}

function cleanseClass(pct: number): string {
  if (pct >= 100) return 'text-green'
  if (pct >= 60) return 'text-cyan'
  return 'text-yellow'
}

export function CleansingGrid({ siloData }: CleansingGridProps) {
  const cleanseSilo = useDataStore((s) => s.cleanseSilo)

  return (
    <div className="cleanse-grid">
      {siloData.map((d) => {
        const complete = d.cleansePct >= 100
        return (
          <div key={d.siloId} className="glass-panel cleanse-card">
            <div className="cleanse-card-head">
              <h4>{d.name}</h4>
              <span className="cleanse-shards">
                <i className="fa-solid fa-layer-group" /> {d.shardCount} 샤드
              </span>
            </div>
            <div className="cleanse-records">
              원본 레코드 <strong>{formatNumber(d.records)}</strong> 건
            </div>
            <div className="cleanse-progress-row">
              <span className="cleanse-label">정제율</span>
              <span className={`cleanse-pct ${cleanseClass(d.cleansePct)}`}>{d.cleansePct}%</span>
            </div>
            <div className="silo-bar-track">
              <div
                className={`silo-bar-fill${complete ? ' done' : ''}`}
                style={{ width: `${d.cleansePct}%` }}
              />
            </div>
            <button
              type="button"
              className="model-action deploy cleanse-run-btn"
              disabled={complete}
              onClick={() => cleanseSilo(d.siloId)}
            >
              <i className={`fa-solid ${complete ? 'fa-check' : 'fa-broom'}`} />{' '}
              {complete ? '정제 완료' : '정제 실행'}
            </button>
          </div>
        )
      })}
    </div>
  )
}
