import { describe, expect, test } from 'vitest'
import {
  mapMetricsToChartPoints,
  mapMetricsToMonitorPoints,
  mapUsageToSilos,
  siloIdToNumber,
} from '@/api/mappers'
import type { MetricSample, ResourceUsageSummary } from '@/api/client'

const usage = (siloId: string, cpu: number): ResourceUsageSummary => ({
  silo_id: siloId,
  last_sample_at: '2026-08-21T00:00:00Z',
  cpu_pct: cpu,
  mem_pct: 50,
  gpu_pct: null,
  disk_pct: null,
  over_budget: false,
})

const sample = (metric: string, value: number, ts: string, node = 'silo-1'): MetricSample => ({
  node_id: node,
  model_name: 'm',
  version: '1.0.0',
  metric,
  value,
  timestamp: ts,
})

describe('siloIdToNumber', () => {
  test('extracts trailing digits and falls back to offset index', () => {
    expect(siloIdToNumber('silo-3', 0)).toBe(3)
    expect(siloIdToNumber('hospital-A', 2)).toBe(1002)
  })
})

describe('mapUsageToSilos', () => {
  test('maps usage with limit thresholds and defaults', () => {
    // Arrange: silo-1은 임계값 지정, silo-2는 미지정
    const silos = mapUsageToSilos(
      [usage('silo-1', 62.4), usage('silo-2', 30)],
      [
        {
          silo_id: 'silo-1',
          cpu_pct_max: 70,
          mem_pct_max: null,
          gpu_pct_max: null,
          disk_pct_max: null,
        },
      ],
    )

    // Assert
    expect(silos[0]).toMatchObject({ id: 1, name: 'silo-1', cpu: 62, disk: 0 })
    expect(silos[0].thresholds).toEqual({ cpu: 70, mem: 80, disk: 90 })
    expect(silos[1].thresholds).toEqual({ cpu: 85, mem: 80, disk: 90 })
  })
})

describe('mapMetricsToChartPoints', () => {
  test('groups by timestamp, averages silos, and scales accuracy to percent', () => {
    // Arrange: t1에 두 사일로(0.8, 0.9), t0에 하나(0.7) — 시간순 정렬 확인
    const points = mapMetricsToChartPoints([
      sample('accuracy', 0.8, '2026-08-21T00:05:00Z', 'silo-1'),
      sample('accuracy', 0.9, '2026-08-21T00:05:00Z', 'silo-2'),
      sample('accuracy', 0.7, '2026-08-21T00:00:00Z'),
    ])

    // Assert
    expect(points).toEqual([
      { round: 0, accuracy: 70, loss: 0 },
      { round: 1, accuracy: 85, loss: 0 },
    ])
  })
})

describe('mapMetricsToMonitorPoints', () => {
  test('pairs throughput and latency series by round index', () => {
    const points = mapMetricsToMonitorPoints(
      [sample('throughput_rps', 51.26, '2026-08-21T00:00:00Z')],
      [
        sample('latency_ms', 130.5, '2026-08-21T00:00:00Z'),
        sample('latency_ms', 128.1, '2026-08-21T00:05:00Z'),
      ],
    )

    expect(points).toEqual([
      { round: 0, throughput: 51.3, latency: 130.5, drift: 0 },
      { round: 1, throughput: 0, latency: 128.1, drift: 0 },
    ])
  })
})
