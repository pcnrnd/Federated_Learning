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

  const siloData = useMemo<SiloData[]>(
    () =>
      silos.filter((s) => dataBySilo[s.id] !== undefined).map((s) => {
        const d = dataBySilo[s.id]
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
              조회된 정제 결과가 없습니다. 연결 상태와 정제 작업 현황을 확인하세요.
            </div>
          ) : (
            <CleansingGrid siloData={siloData} />
          )}
          <div className="data-subhead">
            <i className="fa-solid fa-diagram-project" /> 샤딩 분할 흐름 (원본 → N 샤드)
          </div>
          {siloData.length === 0 ? (
            <div className="deploy-empty">샤딩 다이어그램을 그릴 정제 결과가 없습니다.</div>
          ) : (
            <ShardingDiagram siloData={siloData} />
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
