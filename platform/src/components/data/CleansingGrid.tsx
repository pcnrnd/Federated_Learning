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

/**
 * `<step>.<항목>.<세부>` 형태의 카운터 키를 `.` 경계마다 줄바꿈 기회(<wbr>)와 함께 렌더링한다.
 * 표시 문자열은 그대로이고, 좁은 카드에서 긴 키가 카드 밖으로 밀려 잘리는 것만 막는다.
 */
function CounterKey({ name }: { name: string }) {
  const parts = name.split('.')
  return (
    <>
      {parts.map((part, i) => (
        <span key={i}>
          {i > 0 && (
            <>
              .<wbr />
            </>
          )}
          {part}
        </span>
      ))}
    </>
  )
}

/**
 * step별 적용 건수를 카운터 하나당 칩 하나로, 들어온 순서 그대로 나열한다.
 * 상태 칩 행과 분리된 블록이라 카운터가 많아도 가로로 넘치지 않고 줄바꿈된다.
 */
function CounterList({ counters }: { counters: Record<string, number> }) {
  return (
    <div className="cleanse-counters" title="정제 step별 적용 건수">
      {Object.entries(counters).map(([step, n]) => (
        <span key={step} className="cleanse-counter">
          <CounterKey name={step} /> {formatNumber(n)}
        </span>
      ))}
    </div>
  )
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
              <>
                <div className="cleanse-progress-row">
                  <span className={`dep-state-badge ${liveState.cls}`}>{liveState.label}</span>
                </div>
                {d.stepCounters && Object.keys(d.stepCounters).length > 0 && (
                  <CounterList counters={d.stepCounters} />
                )}
              </>
            )}
          </div>
        )
      })}
    </div>
  )
}
