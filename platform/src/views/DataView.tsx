import { useMemo } from 'react'
import { CleansingGrid } from '@/components/data/CleansingGrid'
import { JobScheduler } from '@/components/data/JobScheduler'
import { ShardingDiagram } from '@/components/data/ShardingDiagram'
import { formatNumber } from '@/lib/format'
import { useDataStore } from '@/store/useDataStore'
import { useSiloStore } from '@/store/useSiloStore'
import type { CleaningJobStatus, SiloData } from '@/types/simulation'

const JOB_STATUS_META: Record<CleaningJobStatus, { label: string; cls: string }> = {
  pending: { label: '대기', cls: 'dep-state-pending' },
  running: { label: '진행중', cls: 'dep-state-deploying' },
  completed: { label: '완료', cls: 'dep-state-done' },
  partial: { label: '부분 실패', cls: 'dep-state-failed' },
  failed: { label: '실패', cls: 'dep-state-failed' },
}

/** 실서버 정제 잡 현황 표 — 라이브 폴링이 채운 목록만 그린다 */
function LiveCleaningJobs() {
  const liveJobs = useDataStore((s) => s.liveCleaningJobs)
  if (liveJobs.length === 0) return null

  return (
    <>
      <div className="data-subhead">
        <i className="fa-solid fa-list-check" /> 정제 잡 현황 (실서버)
      </div>
      <div className="model-table-wrapper">
        <table className="model-table">
          <thead>
            <tr>
              <th>잡 ID</th>
              <th>레시피</th>
              <th>데이터셋</th>
              <th>상태</th>
              <th className="ta-right">행수 (입력→출력)</th>
              <th>step 카운터</th>
            </tr>
          </thead>
          <tbody>
            {liveJobs.map((job) => {
              const meta = JOB_STATUS_META[job.status]
              return (
                <tr key={job.jobId}>
                  <td className="model-version-cell">{job.jobId}</td>
                  <td className="model-algo-cell">{job.recipe}</td>
                  <td className="model-project-cell">{job.datasetLabel}</td>
                  <td>
                    <span className={`dep-state-badge ${meta.cls}`}>{meta.label}</span>
                  </td>
                  <td className="ta-right text-cyan">
                    {formatNumber(job.totalRowsIn)} → {formatNumber(job.totalRowsOut)}
                  </td>
                  <td className="model-date-cell">
                    {Object.entries(job.counters)
                      .map(([step, n]) => `${step} ${formatNumber(n)}`)
                      .join(' · ') || '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

export function DataView() {
  const silos = useSiloStore((s) => s.silos)
  const dataBySilo = useDataStore((s) => s.dataBySilo)

  // 사일로 식별자는 useSiloStore(단일 소스), 파이프라인 수치는 useDataStore에서 병합
  const siloData = useMemo<SiloData[]>(
    () =>
      silos.map((s) => {
        const d = dataBySilo[s.id] ?? { cleansePct: 0, shardCount: 1, records: 0 }
        return { siloId: s.id, name: s.name, ...d }
      }),
    [silos, dataBySilo],
  )

  return (
    <div className="tab-pane">
      <div className="glass-panel content-card full-card">
        <div className="card-header">
          <h3>
            <i className="fa-solid fa-broom" /> 사일로 데이터 정제 · 샤딩
          </h3>
          <span className="desc">
            Data cleansing progress &amp; shard distribution across silos.
          </span>
        </div>
        <div className="card-body">
          {siloData.length === 0 ? (
            <div className="deploy-empty">
              등록된 사일로가 없습니다. “사일로 리소스” 탭에서 사일로를 등록하세요.
            </div>
          ) : (
            <>
              <CleansingGrid siloData={siloData} />
              <LiveCleaningJobs />
              <div className="data-subhead">
                <i className="fa-solid fa-diagram-project" /> 샤딩 분할 흐름 (원본 → N 샤드)
              </div>
              <ShardingDiagram siloData={siloData} />
            </>
          )}
        </div>
      </div>

      <div className="glass-panel content-card full-card">
        <div className="card-header">
          <h3>
            <i className="fa-solid fa-calendar-check" /> 배치 스케줄러 · 데이터 파이프라인
          </h3>
          <span className="desc">
            Batch scheduler — job dependencies, parallel execution &amp; state transitions.
          </span>
        </div>
        <div className="card-body">
          <JobScheduler />
        </div>
      </div>
    </div>
  )
}
