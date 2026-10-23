import { useState } from 'react'
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
  retry_wait: { label: '재시도 대기', cls: 'dep-state-pending' },
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

/** 접힌 상태에서 보여 줄 카운터 칩 수 — 카드·표 행 높이를 제한한다 */
export const COUNTER_PREVIEW_LIMIT = 8

/**
 * step별 적용 건수를 카운터 하나당 칩 하나로, 들어온 순서 그대로 나열한다.
 * 사일로 카드와 정제 잡 표가 같이 쓰며, 많으면 처음 몇 개만 보이고 "더 보기"로 펼친다.
 */
export function CounterList({ counters }: { counters: Record<string, number> }) {
  const [expanded, setExpanded] = useState(false)
  const entries = Object.entries(counters)
  if (entries.length === 0) return <span className="cleanse-counter-empty">—</span>
  const hidden = entries.length - COUNTER_PREVIEW_LIMIT
  const visible = expanded || hidden <= 0 ? entries : entries.slice(0, COUNTER_PREVIEW_LIMIT)
  return (
    <div className="cleanse-counters" title="정제 step별 적용 건수">
      {visible.map(([step, n]) => (
        <span key={step} className="cleanse-counter">
          <CounterKey name={step} /> {formatNumber(n)}
        </span>
      ))}
      {hidden > 0 && (
        <button
          type="button"
          className="cleanse-counter-more"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? '접기' : `+${hidden} 더 보기`}
        </button>
      )}
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
              <span className="cleanse-label">{liveState ? '실행 단계 진행률' : '정제율'}</span>
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
