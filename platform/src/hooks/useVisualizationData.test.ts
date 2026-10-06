import { describe, expect, test } from 'vitest'
import { hideStaleCharts, type VizQuery, type VizSnapshot } from '@/hooks/useVisualizationData'
import type { HistogramPayload, SiloBarPayload, TimeSeriesPayload, TopologyPayload } from '@/api/client'

const QUERY: VizQuery = {
  modelName: 'alpha',
  modelVersion: '1.0.0',
  trendMetric: 'latency_ms',
  resourceMetric: 'cpu_pct',
  baselineKey: 'alpha::1.0.0::age',
}

const SNAPSHOT: VizSnapshot = {
  data: {
    trend: { series: [] } as unknown as TimeSeriesPayload,
    resourceBar: { items: [] } as unknown as SiloBarPayload,
    topology: { nodes: [], edges: [] } as unknown as TopologyPayload,
    histogram: { key: 'alpha::1.0.0::age', payload: {} as HistogramPayload },
    baselines: [{ model_name: 'alpha', version: '1.0.0', feature: 'age', bin_count: 5 }],
  },
  failed: ['participation', 'roundBar'],
  query: QUERY,
  loading: [],
}

describe('hideStaleCharts', () => {
  test('returns the snapshot unchanged when the query still matches', () => {
    expect(hideStaleCharts(SNAPSHOT, { ...QUERY })).toBe(SNAPSHOT)
  })

  test('hides the trend when the metric changed so old values are not drawn with the new scale', () => {
    const shown = hideStaleCharts(SNAPSHOT, { ...QUERY, trendMetric: 'accuracy' })

    expect(shown.loading).toEqual(['trend'])
    expect(shown.data.trend).toBeUndefined()
    expect(shown.data.resourceBar).toBe(SNAPSHOT.data.resourceBar)
    expect(shown.data.histogram).toBe(SNAPSHOT.data.histogram)
  })

  test.each([
    ['modelName', 'beta'],
    ['modelVersion', '2.0.0'],
  ] as const)('hides the trend when %s changed', (field, value) => {
    expect(hideStaleCharts(SNAPSHOT, { ...QUERY, [field]: value }).loading).toEqual(['trend'])
  })

  test('hides only the resource bar when the resource metric changed', () => {
    const shown = hideStaleCharts(SNAPSHOT, { ...QUERY, resourceMetric: 'mem_pct' })

    expect(shown.loading).toEqual(['resourceBar'])
    expect(shown.data.resourceBar).toBeUndefined()
    expect(shown.data.trend).toBe(SNAPSHOT.data.trend)
  })

  test('hides the histogram but keeps the baseline list when the baseline changed', () => {
    const shown = hideStaleCharts(SNAPSHOT, { ...QUERY, baselineKey: 'alpha::1.0.0::income' })

    expect(shown.loading).toEqual(['histogram'])
    expect(shown.data.histogram).toBeUndefined()
    expect(shown.data.baselines).toBe(SNAPSHOT.data.baselines)
  })

  test('keeps selection-independent charts and their failures', () => {
    const shown = hideStaleCharts(SNAPSHOT, {
      modelName: 'beta',
      modelVersion: '2.0.0',
      trendMetric: 'accuracy',
      resourceMetric: 'gpu_pct',
      baselineKey: null,
    })

    expect(shown.loading).toEqual(['trend', 'resourceBar', 'histogram'])
    expect(shown.data.topology).toBe(SNAPSHOT.data.topology)
    expect(shown.failed).toEqual(['participation', 'roundBar'])
  })

  test('drops a stale failure so the card waits for the new response', () => {
    const failedTrend: VizSnapshot = { ...SNAPSHOT, failed: ['trend', 'topology'] }

    const shown = hideStaleCharts(failedTrend, { ...QUERY, trendMetric: 'accuracy' })

    expect(shown.failed).toEqual(['topology'])
    expect(shown.loading).toEqual(['trend'])
  })
})
