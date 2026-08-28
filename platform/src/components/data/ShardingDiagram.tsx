import { formatNumber } from '@/lib/format'
import type { SiloData } from '@/types/simulation'

interface ShardingDiagramProps {
  siloData: SiloData[]
}

/**
 * 원본 데이터 → N개 샤드 분할 흐름을 박스 그리드로 표현.
 * 사일로별로 한 행: [원본] → [샤드 1..N]
 */
export function ShardingDiagram({ siloData }: ShardingDiagramProps) {
  return (
    <div className="shard-diagram">
      {siloData.map((d) => {
        const perShard = Math.round(d.records / d.shardCount)
        return (
          <div key={d.siloId} className="shard-row">
            <div className="shard-source">
              <span className="shard-source-name">{d.name}</span>
              <span className="shard-source-meta">{formatNumber(d.records)} 건</span>
            </div>
            <i className="fa-solid fa-arrow-right-long shard-arrow" />
            <div className="shard-boxes">
              {Array.from({ length: d.shardCount }, (_, i) => (
                <div key={i} className="shard-box" title={`샤드 ${i + 1} · 약 ${formatNumber(perShard)}건`}>
                  <i className="fa-solid fa-cube" />
                  <span>S{i + 1}</span>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
