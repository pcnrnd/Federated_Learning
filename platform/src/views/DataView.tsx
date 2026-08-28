import { useMemo } from 'react'
import { CleansingGrid } from '@/components/data/CleansingGrid'
import { JobScheduler } from '@/components/data/JobScheduler'
import { ShardingDiagram } from '@/components/data/ShardingDiagram'
import { useDataStore } from '@/store/useDataStore'
import { useSiloStore } from '@/store/useSiloStore'
import type { SiloData } from '@/types/simulation'

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
