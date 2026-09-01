import { formatNumber } from '@/lib/format'
import type { SiloData } from '@/types/simulation'

interface CleansingGridProps {
  siloData: SiloData[]
}

function cleanseClass(pct: number): string {
  if (pct >= 100) return 'text-green'
  if (pct >= 60) return 'text-cyan'
  return 'text-yellow'
}

/** 실서버 샤드 상태 → 배포 타임라인 상태 칩 클래스/라벨 재사용 */
const SHARD_STATE_META: Record<
  NonNullable<SiloData['cleanseStatus']>,
  { label: string; cls: string }
> = {
  pending: { label: '대기', cls: 'dep-state-pending' },
  running: { label: '정제중', cls: 'dep-state-deploying' },
  completed: { label: '정제 완료', cls: 'dep-state-done' },
  failed: { label: '실패', cls: 'dep-state-failed' },
}

function counterText(counters: Record<string, number>): string {
  return Object.entries(counters)
    .map(([step, n]) => `${step} ${formatNumber(n)}`)
    .join(' · ')
}

export function CleansingGrid({ siloData }: CleansingGridProps) {
  return (
    <div className="cleanse-grid">
      {siloData.map((d) => {
        const complete = d.cleansePct >= 100
        const liveState = d.cleanseStatus ? SHARD_STATE_META[d.cleanseStatus] : null
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
            {liveState && (
              <div className="cleanse-progress-row">
                <span className={`dep-state-badge ${liveState.cls}`}>{liveState.label}</span>
                {d.stepCounters && Object.keys(d.stepCounters).length > 0 && (
                  <span className="cleanse-label" title="정제 step별 적용 건수">
                    {counterText(d.stepCounters)}
                  </span>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
