import '@/test/currentSnapshotSsr'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import {
  CONTROL_CLEANING_FIELD_IDS,
  CONTROL_LIVE_JOB_FIELD_IDS,
  CONTROL_TRAINING_FIELD_IDS,
  LIVE_DRIFT_POLICY_FIELD_IDS,
  MAIN_MODEL_FIELD_IDS,
  MAIN_PIPELINE_FIELD_IDS,
  PIPE_CLEANING_FIELD_IDS,
  PIPE_TRAINING_FIELD_IDS,
  RETRAINING_FIELD_IDS,
} from '@/lib/pipelineFields'
import { LIVE_JOB_SELECT_REASON } from '@/lib/uiMode'
import { trainingJobActionPath } from '@/lib/trainingJobPaths'
import type { TrainingJobApi } from '@/api/client'

function assertIds(html: string, ids: readonly string[]) {
  for (const id of ids) {
    expect(html, `missing id=${id}`).toContain(`id="${id}"`)
  }
}

async function prepareMode(mockEnabled: boolean, apiBase: string) {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE', apiBase)
  const { useSimulationStore } = await import('@/store/useSimulationStore')
  useSimulationStore.setState({ mockEnabled })
  return useSimulationStore
}

beforeEach(() => {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE', 'http://central')
})
afterEach(() => {
  vi.unstubAllEnvs()
})

test('라이브 JobScheduler는 데모와 같은 테이블 골격을 유지한다', async () => {
  await prepareMode(false, 'http://central')
  const { JobScheduler } = await import('@/components/data/JobScheduler')
  const html = renderToStaticMarkup(<JobScheduler />)
  expect(html).toContain('작업명')
  expect(html).toContain('파이프라인 등록')
})

test('미설정 API에서도 ControlPanel·NewModelForm 공통 카드가 유지된다', async () => {
  await prepareMode(false, '')
  const { ControlPanel } = await import('@/components/controls/ControlPanel')
  const { NewModelForm } = await import('@/components/models/NewModelForm')
  expect(renderToStaticMarkup(<ControlPanel />)).toContain('시뮬레이션 구성 및 제어')
  expect(renderToStaticMarkup(<NewModelForm defaultProject="p" onClose={() => {}} />)).toContain('VITE_API_BASE')
})

test('라이브 NodeCard 어댑터는 CPU 미수집을 대시로 렌더하고 IDLE 배지를 표시하지 않는다', async () => {
  const { silosToDisplayNodes } = await import('@/lib/displayNodes')
  const { NodeCard } = await import('@/components/nodes/NodeCard')
  const node = silosToDisplayNodes(
    [
      {
        id: 2,
        name: 'S2',
        endpoint: 'x',
        collectIntervalSec: 1,
        cpu: null,
        mem: null,
        disk: null,
        thresholds: { cpu: 1, mem: 1, disk: 1 },
      },
    ],
    {},
  )[0]
  expect(node.statusUnavailable).toBe(true)
  const html = renderToStaticMarkup(<NodeCard node={node} interactive={false} allNodes={[node]} />)
  expect(html).toContain('progress-text')
  expect(html).toContain('— (미수집)')
  expect(html).toContain('status-unobserved')
  expect(html).not.toContain('>IDLE<')
})

test('NewModelForm·UnifiedPipelineForm·Retraining·Drift는 세 모드에서 동일 field id를 유지한다', async () => {
  const modes: Array<{ mock: boolean; api: string }> = [
    { mock: true, api: 'http://central' },
    { mock: false, api: 'http://central' },
    { mock: false, api: '' },
  ]

  for (const { mock, api } of modes) {
    await prepareMode(mock, api)
    const { useMonitoringStore } = await import('@/store/useMonitoringStore')
    useMonitoringStore.setState({ settingsExpanded: true })
    const { NewModelForm } = await import('@/components/models/NewModelForm')
    const { UnifiedPipelineForm } = await import('@/components/data/UnifiedPipelineForm')
    const { RetrainingPanel } = await import('@/components/analytics/RetrainingPanel')
    const { DriftSettingsPanel } = await import('@/components/analytics/DriftSettingsPanel')
    const { ControlPanel } = await import('@/components/controls/ControlPanel')

    const modelHtml = renderToStaticMarkup(<NewModelForm defaultProject="p" onClose={() => {}} />)
    assertIds(modelHtml, MAIN_MODEL_FIELD_IDS)

    const pipeHtml = renderToStaticMarkup(<UnifiedPipelineForm onClose={() => {}} />)
    assertIds(pipeHtml, MAIN_PIPELINE_FIELD_IDS)
    assertIds(pipeHtml, PIPE_CLEANING_FIELD_IDS)
    assertIds(pipeHtml, PIPE_TRAINING_FIELD_IDS)

    const retrainHtml = renderToStaticMarkup(<RetrainingPanel />)
    assertIds(retrainHtml, RETRAINING_FIELD_IDS)

    const driftHtml = renderToStaticMarkup(<DriftSettingsPanel />)
    assertIds(driftHtml, LIVE_DRIFT_POLICY_FIELD_IDS)

    const controlHtml = renderToStaticMarkup(<ControlPanel />)
    assertIds(controlHtml, CONTROL_TRAINING_FIELD_IDS)
    assertIds(controlHtml, CONTROL_CLEANING_FIELD_IDS)
    assertIds(controlHtml, CONTROL_LIVE_JOB_FIELD_IDS)
  }
})

test('라이브 NewModelForm은 데모 정확도·라운드 기본값 90/20을 표시하지 않는다', async () => {
  await prepareMode(false, 'http://central')
  const { NewModelForm } = await import('@/components/models/NewModelForm')
  const html = renderToStaticMarkup(<NewModelForm defaultProject="p" onClose={() => {}} />)
  expect(html).not.toMatch(/id="new-model-accuracy"[^>]*value="90"/)
  expect(html).not.toMatch(/id="new-model-rounds"[^>]*value="20"/)
  expect(html).toContain('placeholder="—"')
})

test('ControlPanel은 두 작업 옵션과 미선택 시 일시정지·취소 비활성 안내를 렌더한다', async () => {
  await prepareMode(false, 'http://central')
  const { useLiveTrainingStore } = await import('@/store/useLiveTrainingStore')
  const jobs: TrainingJobApi[] = [
    {
      job_id: 'job-first',
      model_name: 'm',
      version: '1',
      status: 'active',
      rounds_completed: 0,
      max_rounds: 2,
      current_round_id: 'r1',
    },
    {
      job_id: 'job/second',
      model_name: 'm2',
      version: '1',
      status: 'paused',
      rounds_completed: 1,
      max_rounds: 3,
      current_round_id: 'r2',
    },
  ]
  useLiveTrainingStore.setState({ jobs, rounds: [], error: null, pending: false, pollPending: false, observers: 0 })
  const { ControlPanel } = await import('@/components/controls/ControlPanel')
  const html = renderToStaticMarkup(<ControlPanel />)
  expect(html).toContain('id="control-live-training-job"')
  expect(html).toContain('value="job-first"')
  expect(html).toContain('value="job/second"')
  expect(html).toContain(`title="${LIVE_JOB_SELECT_REASON}"`)
  expect(html).toContain('disabled')
})

test('trainingJobActionPath는 슬래시 포함 job_id를 encodeURIComponent 한다', () => {
  expect(trainingJobActionPath('job/second', 'pause')).toBe('/api/training-jobs/job%2Fsecond/pause')
  expect(trainingJobActionPath('job/second', 'cancel')).toBe('/api/training-jobs/job%2Fsecond/cancel')
})

test('UnifiedPipelineForm은 liveError·training store error를 각각 role=alert로 표시한다', async () => {
  await prepareMode(false, 'http://central')
  const { useDataStore } = await import('@/store/useDataStore')
  const { useLiveTrainingStore } = await import('@/store/useLiveTrainingStore')
  useDataStore.setState({ liveError: '정제 저장 실패' })
  useLiveTrainingStore.setState({ error: '학습 등록 실패', pending: false })
  const { UnifiedPipelineForm } = await import('@/components/data/UnifiedPipelineForm')
  const html = renderToStaticMarkup(<UnifiedPipelineForm onClose={() => {}} />)
  expect(html).toContain('role="alert"')
  expect(html).toContain('정제 저장 실패')
  expect(html).toContain('학습 등록 실패')
})

test('PipelineLiveResults는 정제 카운터·라운드 결과 섹션을 렌더한다', async () => {
  const { useDataStore } = await import('@/store/useDataStore')
  const { useLiveTrainingStore } = await import('@/store/useLiveTrainingStore')
  useDataStore.setState({
    liveCleaningJobs: [
      {
        jobId: 'clean-1',
        status: 'running',
        progress: 42,
        recipe: 'r',
        datasetLabel: 'd',
        totalRowsIn: 10,
        totalRowsOut: 8,
        counters: { filter: 2 },
        errors: ['step failed'],
        updatedAt: '2026-01-01T00:00:00Z',
      },
    ],
  })
  useLiveTrainingStore.setState({
    jobs: [
      {
        job_id: 'train-1',
        model_name: 'm',
        version: '1',
        status: 'active',
        rounds_completed: 1,
        max_rounds: 2,
        current_round_id: 'round-1',
      },
    ],
    rounds: [
      {
        round_id: 'round-1',
        status: 'completed',
        contributors: [],
        total_samples: 5,
        parent_round_id: 'parent',
        base_checksum: 'base',
        result: {
          result_id: 'res-1',
          checksum: 'abc',
          parameters: [1, 2],
          parameter_dim: 2,
          total_samples: 5,
          format: 'ridge_gradient_v1',
          features: ['x1', 'x2'],
          target: 'y',
        },
      },
    ],
    pending: false,
    error: null,
    pollPending: false,
    observers: 0,
  })
  const { PipelineLiveResults } = await import('@/components/data/PipelineLiveResults')
  const html = renderToStaticMarkup(<PipelineLiveResults />)
  expect(html).toContain('step 카운터')
  expect(html).toContain('step failed')
  expect(html).toContain('res-1')
  expect(html).toContain('abc')
})
