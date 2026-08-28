import { describe, expect, test } from 'vitest'
import { deriveStorageUnits, STORAGE_UNIT_RANGE } from '@/lib/storage'

const data = (shardCount: number, cleansePct: number, records = 1000) => ({
  shardCount,
  cleansePct,
  records,
})

describe('deriveStorageUnits', () => {
  test('keeps the unit count within 1~3 for any silo id', () => {
    for (let id = 1; id <= 40; id++) {
      const units = deriveStorageUnits(id, data(7, 50))
      expect(units.length).toBeGreaterThanOrEqual(STORAGE_UNIT_RANGE.min)
      expect(units.length).toBeLessThanOrEqual(STORAGE_UNIT_RANGE.max)
    }
  })

  test('never creates more storages than there are shards', () => {
    // 샤드 1개짜리 노드(증설 직후 하위 노드)는 저장소도 1개뿐이어야 한다
    const units = deriveStorageUnits(2, data(1, 0))
    expect(units).toHaveLength(1)
    expect(units[0].shardCount).toBe(1)
  })

  test('distributes shards evenly with the remainder going to earlier storages', () => {
    // id 2 → 저장소 3개, 샤드 7개 → 3 / 2 / 2
    const units = deriveStorageUnits(2, data(7, 0))

    expect(units.map((u) => u.shardCount)).toEqual([3, 2, 2])
    expect(units.reduce((s, u) => s + u.shardCount, 0)).toBe(7)
  })

  test('fills cleansed shards from the first storage onward', () => {
    // 샤드 7개 중 57% → 4개 정제 → 3 / 1 / 0
    const units = deriveStorageUnits(2, data(7, 57))

    expect(units.map((u) => u.cleansedShards)).toEqual([3, 1, 0])
    units.forEach((u) => expect(u.cleansedShards).toBeLessThanOrEqual(u.shardCount))
  })

  test('marks nothing cleansed at 0% and everything at 100%', () => {
    const none = deriveStorageUnits(2, data(7, 0))
    const all = deriveStorageUnits(2, data(7, 100))

    expect(none.reduce((s, u) => s + u.cleansedShards, 0)).toBe(0)
    expect(all.map((u) => u.cleansedShards)).toEqual(all.map((u) => u.shardCount))
  })

  test('splits records in proportion to the shard split', () => {
    const units = deriveStorageUnits(2, data(7, 0, 700))

    expect(units.map((u) => u.records)).toEqual([300, 200, 200])
  })

  test('is deterministic for the same silo id', () => {
    expect(deriveStorageUnits(5, data(6, 40))).toEqual(deriveStorageUnits(5, data(6, 40)))
  })
})
