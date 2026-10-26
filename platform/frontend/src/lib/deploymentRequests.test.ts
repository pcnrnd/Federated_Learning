import { expect, test } from 'vitest'
import { modelKey, mapApiDeployments } from '@/api/mappers'
import type { DeploymentEntryApi } from '@/api/client'
import type { Silo } from '@/types/simulation'
import { deploymentPayload, parseDeploymentEnv } from './deploymentRequests'

const silos: Silo[] = [1, 2].map((id) => ({ id, serverId: id === 1 ? 'silo-1' : 'silo-01', name: `표시${id}`,
  endpoint: '', collectIntervalSec: 5, cpu: null, mem: null, disk: null, thresholds: { cpu: null, mem: null, disk: null } }))

test('환경변수 값의 equals/공백을 보존하고 중복·예약·잘못된 이름을 거부한다', () => {
  expect(parseDeploymentEnv('APP=a=b\nOTHER= keep spaces \n')).toEqual({ APP: 'a=b', OTHER: ' keep spaces ' })
  for (const value of ['APP=1\nAPP=2', 'MODEL_NAME=spoof', 'BAD-KEY=a', 'APP', 'APP=a\0b']) {
    expect(() => parseDeploymentEnv(value)).toThrow()
  }
})

test('모든 전략은 선택한 원 서버 ID/env를 보내며 batch에만 interval을 보낸다', () => {
  for (const strategy of ['realtime', 'batch', 'edge'] as const) {
    const payload = deploymentPayload({ modelId: modelKey('기관/a', '1.0.0'), strategy,
      targetSiloIds: [2], intervalSec: 30, env: { APP: 'value' } }, silos)
    expect(payload).toMatchObject({ model_name: '기관/a', target_node_ids: ['silo-01'], env: { APP: 'value' } })
    expect(payload.interval_seconds).toBe(strategy === 'batch' ? 30 : undefined)
  }
  const base = { modelId: modelKey('m', '1.0.0'), strategy: 'batch' as const, intervalSec: 30 }
  for (const ids of [[1, 99], [1, 1]]) expect(() => deploymentPayload({ ...base, targetSiloIds: ids }, silos)).toThrow()
  expect(() => deploymentPayload({ ...base, targetSiloIds: [1], intervalSec: 1.5 }, silos)).toThrow()
})

test('서버 일정/부분 실패/실제 endpoint와 내부 포트 snapshot을 구분해 매핑한다', () => {
  const response: DeploymentEntryApi = { deployment_id: 'actual', model_name: 'm', version: '1.0.0', image_tag: 'tag',
    strategy: 'batch', target_node_ids: ['silo-01'], status: 'failed', created_at: '2026-10-19T00:00:00Z',
    previous_deployment_id: null, error: '확인 실패', expected_image_id: 'sha256:actual',
    configuration: { model_name: 'm', version: '1.0.0', strategy: 'batch', target_node_ids: ['silo-01'],
      env: { APP: 'saved' }, inference_port: 8600, interval_seconds: 30 },
    target_results: { 'silo-01': { status: 'failed', endpoint: 'http://silo-01:31001', error_code: 'ValueError' } },
    is_schedule: true, schedule_active: false, occurrence: 1, next_due_at: 'next', cleanup_pending: true }
  expect(mapApiDeployments([response])[0]).toMatchObject({ state: 'failed', targetNodeIds: ['silo-01'],
    env: { APP: 'saved' }, inferencePort: 8600, intervalSec: 30, imageId: 'sha256:actual',
    isSchedule: true, scheduleActive: false, occurrence: 1, cleanupPending: true,
    targets: { 'silo-01': { endpoint: 'http://silo-01:31001', status: 'failed' } } })
})
