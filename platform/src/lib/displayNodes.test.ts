import { describe, expect, test } from 'vitest'
import { silosToDisplayNodes } from '@/lib/displayNodes'
import type { Silo } from '@/types/simulation'

const silo: Silo = {
  id: 1,
  name: '실서버 기관',
  endpoint: 'tcp://x',
  collectIntervalSec: 15,
  cpu: null,
  mem: null,
  disk: null,
  thresholds: { cpu: 85, mem: 80, disk: 90 },
}

describe('silosToDisplayNodes', () => {
  test('미수집 CPU·분포는 관측값처럼 0/50%로 노출하지 않는다', () => {
    const [node] = silosToDisplayNodes([silo], {})
    expect(node.metricUnavailable?.cpu).toBe(true)
    expect(node.metricUnavailable?.distribution).toBe(true)
    expect(node.normalPct).toBe(0)
    expect(node.abnormalPct).toBe(0)
  })

  test('정제 레코드가 있을 때만 size와 cleanseProgress를 채운다', () => {
    const [node] = silosToDisplayNodes([silo], { 1: { cleansePct: 72, shardCount: 3, records: 1200 } })
    expect(node.metricUnavailable?.size).toBe(false)
    expect(node.size).toBe(1200)
    expect(node.cleanseProgressPct).toBe(72)
  })
})
