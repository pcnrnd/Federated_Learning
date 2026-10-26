import { describe, expect, test } from 'vitest'
import { liveModelRequest, mapLivePackages } from './liveModels'
import { modelKey } from '@/api/mappers'
import type { LiveModelDraft } from '@/types/simulation'

const draft: LiveModelDraft = { mode: 'training', round_id: 'real-round', version: '', name: '', weights_path: '' }

test('완료 결과 등록은 실제 round ID만 보내고 가중치/성과값을 생성하지 않는다', () => {
  expect(liveModelRequest(draft)).toEqual({ endpoint: '/api/models/from-training', body: { round_id: 'real-round' } })
  expect(liveModelRequest({ ...draft, version: '1.0.2' }).body).toEqual({ round_id: 'real-round', version: '1.0.2' })
})

test('저장 artifact 등록은 사용자 지정한 실제 경로와 모델 정체성을 보낸다', () => {
  expect(liveModelRequest({ ...draft, mode: 'artifact', name: '모델/a', version: '1.2.3', weights_path: '/actual/weights.json' }))
    .toEqual({ endpoint: '/api/models', body: { framework: 'ridge', name: '모델/a', version: '1.2.3', weights_path: '/actual/weights.json' } })
  expect(() => liveModelRequest({ ...draft, round_id: '' })).toThrow()
  expect(() => liveModelRequest({ ...draft, version: 'v1' })).toThrow()
  expect(() => liveModelRequest({ ...draft, mode: 'artifact', name: 'm', version: '1.0.0' })).toThrow()
})

describe('실제 package 상태', () => {
  test.each(['unbuilt', 'building', 'failed', 'unknown'] as const)('%s를 built로 바꾸거나 tag/digest를 채우지 않는다', (status) => {
    const packages = mapLivePackages([{ model_name: 'm', version: '1.0.0', status }])
    expect(packages[modelKey('m', '1.0.0')]).toEqual({ modelId: modelKey('m', '1.0.0'),
      state: status === 'unbuilt' ? 'idle' : status, runtime: '', imageTag: '' })
  })
  test('실제 성공/실패 응답의 image/weights 정체성과 오류만 전달한다', () => {
    const packages = mapLivePackages([
      { model_name: '기관/a', version: '1.0.0', status: 'built', image_tag: 'actual:1', image_digest: 'sha256:image',
        base_image: 'python:3.12-slim', weights_checksum: 'weights-checksum', artifact_id: 'artifact', built_at: 'observed-time' },
      { model_name: '기관%2Fa', version: '1.0.0', status: 'failed', error: '실제 서버 빌드 실패' },
    ])
    expect(Object.keys(packages)).toHaveLength(2)
    expect(packages[modelKey('기관/a', '1.0.0')]).toMatchObject({ state: 'built', imageTag: 'actual:1',
      imageDigest: 'sha256:image', weightsChecksum: 'weights-checksum', builtAt: 'observed-time', runtime: 'python:3.12-slim' })
    expect(packages[modelKey('기관%2Fa', '1.0.0')]).toMatchObject({ state: 'failed', error: '실제 서버 빌드 실패' })
  })
})
