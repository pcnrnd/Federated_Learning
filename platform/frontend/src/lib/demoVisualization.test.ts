import { expect, test, vi } from 'vitest'
import { mapHistogram, mapParticipation, mapSiloBar, mapTimeseriesToLines } from '@/api/mappers'
import type { VizQuery } from '@/hooks/useVisualizationData'
import { demoVisualization } from './demoVisualization'
import { layoutVizTopology } from './vizTopology'
import { registeredTopology } from './registeredTopology'
import { mapRegisteredSilos } from './siloResources'

const query: VizQuery = { modelName: '프로젝트3', modelVersion: 'v3.1', trendMetric: 'accuracy', resourceMetric: 'cpu_pct', baselineKey: null }

test('동일 결정 입력이 기존 차트5종의 DTO와 mapper 계약을 충족한다', () => {
  const random = vi.spyOn(Math, 'random').mockImplementation(() => { throw new Error('random is forbidden') })
  const now = vi.spyOn(Date, 'now').mockImplementation(() => { throw new Error('clock is forbidden') })
  try {
    const first = demoVisualization(query)
    expect(demoVisualization(query)).toEqual(first)
    expect(first.failed).toEqual([])
    expect(first.loading).toEqual([])
    expect(mapTimeseriesToLines(first.data.trend!, 100).series).toHaveLength(6)
    expect(mapParticipation(first.data.participation!).columns).toHaveLength(4)
    expect(mapSiloBar(first.data.roundBar!.payload).values).toEqual([120, 150, 180, 210, 240, 270])
    expect(mapHistogram(first.data.histogram!.payload).values).toEqual([18, 42, 67, 49, 24])
    expect(layoutVizTopology(first.data.topology!).nodes).toHaveLength(7)
    for (let col = 0; col < 4; col++) {
      expect(first.data.participation!.matrix.reduce((sum, row) => sum + row[col]!, 0)).toBe(1170)
    }
  } finally { random.mockRestore(); now.mockRestore() }
})

test('지표 선택은 단위가 맞는 다른 demo값을 제공하고 다른 차트를 바꾸지 않는다', () => {
  const accuracy = demoVisualization(query)
  const latency = demoVisualization({ ...query, trendMetric: 'latency_ms', resourceMetric: 'mem_pct' })
  expect(accuracy.data.trend!.series['silo-1'][0].value).toBe(.76)
  expect(latency.data.trend!.series['silo-1'][0].value).toBe(48)
  expect(latency.data.resourceBar!.items[0].value).toBe(37)
  expect(latency.data.participation).toEqual(accuracy.data.participation)
  expect(latency.data.histogram).toEqual(accuracy.data.histogram)
  expect(latency.data.topology).toEqual(accuracy.data.topology)
})

test('성능 추이 demo는 등락하며 증가하고 값이 지표 범위 안에 있다', () => {
  const series = Object.values(demoVisualization(query).data.trend!.series)
  const values = series.map((points) => points.map((p) => p.value))
  expect(values).toHaveLength(6)
  for (const v of values) {
    expect(v).toHaveLength(4)
    expect(v[3]!).toBeGreaterThan(v[0]!)
    expect(v.every((x) => x > 0 && x <= 1)).toBe(true)
  }
  expect(values.some((v) => v.some((x, j) => j > 0 && x < v[j - 1]!))).toBe(true)
  expect(new Set(values.map((v) => v[3])).size).toBe(6)
})

test('LIVE network는 원서버 식별자와 빈 상태를 보존하고 예시같은 이름을 거르지 않는다', () => {
  const live = mapRegisteredSilos(['silo-1', 'silo-01'].map((silo_id) => ({ silo_id, label: 'demo-like-name',
    base_url: `tcp://${silo_id}:2375`, collect_interval_seconds: 15 })), [], [], [])
  const topology = registeredTopology(live)
  expect(topology.nodes.map((n) => n.id)).toEqual(['central:server', 'silo:silo-1', 'silo:silo-01'])
  expect(new Set(topology.edges.map((e) => e.target)).size).toBe(2)
  expect(live.every((s) => s.cpu === null && s.mem === null)).toBe(true)
  expect(registeredTopology([])).toEqual({ nodes: [], edges: [] })
})
