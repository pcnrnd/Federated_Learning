import type { SiloDataFields } from '@/store/useDataStore'

/** 사일로 하나에 두는 저장소 개수 범위 */
export const STORAGE_UNIT_RANGE = { min: 1, max: 3 } as const

/**
 * 사일로에 속한 저장소 하나(MinIO 인스턴스)와 그 저장소가 보유한 샤드 현황.
 */
export interface StorageUnit {
  /** 사일로 내 순번 (1부터) */
  index: number
  /** 이 저장소가 보유한 샤드 수 */
  shardCount: number
  /** 그중 정제가 끝난 샤드 수 */
  cleansedShards: number
  /** 이 저장소가 보관 중인 레코드 수 */
  records: number
}

/**
 * 사일로 단위 집계값(`SiloData`)에서 저장소 계층을 도출한다.
 *
 * 스토어에는 사일로별 합계만 있으므로 여기서 1~3개 저장소로 갈라 준다.
 * 순전히 id에서 결정되는 결정론적 분배라 렌더할 때마다 흔들리지 않는다.
 * - 저장소 수: id 기반 1~3개, 단 샤드 수보다 많을 수는 없다.
 * - 샤드: 균등 분배 후 나머지를 앞 저장소부터 하나씩.
 * - 정제분: 앞 저장소부터 순서대로 채운다 (정제가 순차 진행되는 것으로 표현).
 */
export function deriveStorageUnits(siloId: number, data: SiloDataFields): StorageUnit[] {
  const totalShards = Math.max(1, data.shardCount)
  const wanted = STORAGE_UNIT_RANGE.min + (siloId % STORAGE_UNIT_RANGE.max)
  const unitCount = Math.min(wanted, totalShards)

  const base = Math.floor(totalShards / unitCount)
  const remainder = totalShards % unitCount

  const pct = Math.min(100, Math.max(0, data.cleansePct))
  // 0%가 아닌데 0개로 보이지 않도록 최소 1개는 정제된 것으로 센다
  let cleansedLeft = pct === 0 ? 0 : Math.max(1, Math.round((totalShards * pct) / 100))

  return Array.from({ length: unitCount }, (_, i) => {
    const shardCount = base + (i < remainder ? 1 : 0)
    const cleansedShards = Math.min(shardCount, cleansedLeft)
    cleansedLeft -= cleansedShards
    return {
      index: i + 1,
      shardCount,
      cleansedShards,
      records: Math.round((data.records * shardCount) / totalShards),
    }
  })
}
