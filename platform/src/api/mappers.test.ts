import { describe, expect, test } from 'vitest'
import {
  mapApiDeployments,
  mapCleaningJobs,
  mapMetricsToChartPoints,
  mapMetricsToMonitorPoints,
  mapModelsToVersions,
  mapUsageToSilos,
  modelKey,
  parseModelKey,
  siloIdToNumber,
} from '@/api/mappers'
import type {
  CleaningJobApi,
  DeploymentEntryApi,
  MetricSample,
  ModelEntryApi,
  ResourceUsageSummary,
} from '@/api/client'

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

const modelEntry = (overrides: Partial<ModelEntryApi> = {}): ModelEntryApi => ({
  name: 'demo-alpha',
  version: '1.0.0',
  framework: 'pytorch',
  weights_path: '/srv/weights/demo.pt',
  metadata: {},
  created_at: '2026-09-01T08:30:00+00:00',
  ...overrides,
})

const deploymentEntry = (overrides: Partial<DeploymentEntryApi> = {}): DeploymentEntryApi => ({
  deployment_id: 'dep-abc',
  model_name: 'demo-alpha',
  version: '1.0.0',
  image_tag: 'fed-model-demo-alpha:1.0.0',
  strategy: 'realtime',
  target_node_ids: ['silo-1', 'silo-2'],
  status: 'running',
  created_at: '2026-09-01T08:45:12+00:00',
  previous_deployment_id: null,
  error: null,
  ...overrides,
})

describe('modelKey / parseModelKey', () => {
  test('round-trips name@version, tolerating @ inside names', () => {
    expect(parseModelKey(modelKey('demo-alpha', '1.0.0'))).toEqual({
      name: 'demo-alpha',
      version: '1.0.0',
    })
    expect(parseModelKey('a@b@2.0.0')).toEqual({ name: 'a@b', version: '2.0.0' })
  })
})

describe('mapModelsToVersions', () => {
  test('promotes versions with a running deployment and reads metadata safely', () => {
    const versions = mapModelsToVersions(
      [
        modelEntry({ metadata: { accuracy: 0.947, algorithm: 'secagg', rounds: 28, note: '메모' } }),
        modelEntry({ version: '0.9.0', metadata: { algorithm: 'unknown-algo' } }),
      ],
      [deploymentEntry()],
    )

    expect(versions[0]).toEqual({
      id: 'demo-alpha@1.0.0',
      project: 'demo-alpha',
      version: '1.0.0',
      status: 'deployed',
      accuracy: 94.7,
      algorithm: 'secagg',
      rounds: 28,
      createdAt: '2026-09-01',
      note: '메모',
    })
    // 알 수 없는 metadata는 기본값으로 폴백, running 배포 없음 → 실험
    expect(versions[1]).toMatchObject({ status: 'experimental', algorithm: 'fedavg', accuracy: 0 })
  })
})

describe('mapApiDeployments', () => {
  test('maps ids, states and target silos', () => {
    const [dep] = mapApiDeployments([deploymentEntry({ status: 'rolled_back' })])
    expect(dep).toEqual({
      id: 'dep-abc',
      modelId: 'demo-alpha@1.0.0',
      modelLabel: 'demo-alpha 1.0.0',
      strategy: 'realtime',
      targetSiloIds: [1, 2],
      state: 'rolled_back',
      ts: '08:45:12',
    })
  })

  test('running maps to done (rollback-eligible)', () => {
    expect(mapApiDeployments([deploymentEntry()])[0].state).toBe('done')
  })
})

const cleaningJob = (overrides: Partial<CleaningJobApi> = {}): CleaningJobApi => ({
  job_id: 'job-1',
  recipe_name: 'basic',
  recipe_version: '1.0.0',
  status: 'completed',
  shards: [
    {
      shard_index: 0,
      silo_id: 'silo-1',
      status: 'completed',
      rows_in: 210,
      rows_out: 182,
      step_counters: { drop_nulls: 20, dedupe: 8 },
    },
    {
      shard_index: 1,
      silo_id: 'silo-2',
      status: 'running',
      rows_in: 0,
      rows_out: 0,
      step_counters: {},
    },
  ],
  total_rows_in: 210,
  total_rows_out: 182,
  aggregated_counters: { drop_nulls: 20, dedupe: 8 },
  dataset_label: 'patients_2026Q3',
  updated_at: '2026-09-01T00:00:00Z',
  ...overrides,
})

describe('mapCleaningJobs', () => {
  test('maps shard status/counters into per-silo data and job summaries', () => {
    const { dataBySilo, jobs } = mapCleaningJobs([cleaningJob()])

    expect(dataBySilo[1]).toEqual({
      cleansePct: 100,
      shardCount: 1,
      records: 210,
      cleanseStatus: 'completed',
      stepCounters: { drop_nulls: 20, dedupe: 8 },
    })
    expect(dataBySilo[2]).toMatchObject({ cleansePct: 0, cleanseStatus: 'running' })

    expect(jobs).toEqual([
      {
        jobId: 'job-1',
        recipe: 'basic@1.0.0',
        status: 'completed',
        datasetLabel: 'patients_2026Q3',
        totalRowsIn: 210,
        totalRowsOut: 182,
        counters: { drop_nulls: 20, dedupe: 8 },
        updatedAt: '2026-09-01T00:00:00Z',
      },
    ])
  })

  test('the newest job (first in list) wins per silo', () => {
    const newest = cleaningJob({ job_id: 'job-new' })
    const older = cleaningJob({
      job_id: 'job-old',
      shards: [
        {
          shard_index: 0,
          silo_id: 'silo-1',
          status: 'failed',
          rows_in: 999,
          rows_out: 0,
          step_counters: {},
        },
      ],
    })

    const { dataBySilo } = mapCleaningJobs([newest, older])
    expect(dataBySilo[1].cleanseStatus).toBe('completed')
    expect(dataBySilo[1].records).toBe(210)
  })

  test('empty job list maps to empty state', () => {
    expect(mapCleaningJobs([])).toEqual({ dataBySilo: {}, jobs: [] })
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
