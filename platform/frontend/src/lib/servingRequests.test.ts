import { expect, test } from 'vitest'
import { comparisonGate, servingInputs } from './servingRequests'
import type { ServingGateDraft } from '@/types/simulation'

const draft: ServingGateDraft = { min_pairs: '2', window_seconds: '60', max_age_seconds: '30',
  max_error_rate: '0', max_mean_abs_difference: '0.25', max_latency_ratio: '' }

test('승격 gate는 명시한 N/구간/최신성/오류/예측 차이를 그대로 보내고 속도 기준은 선택한다', () => {
  expect(comparisonGate(draft)).toEqual({ min_pairs: 2, window_seconds: 60, max_age_seconds: 30,
    max_error_rate: 0, max_mean_abs_difference: .25, max_latency_ratio: null })
  expect(comparisonGate({ ...draft, max_latency_ratio: '1.5' }).max_latency_ratio).toBe(1.5)
  for (const patch of [{ min_pairs: '' }, { min_pairs: '1.5' }, { window_seconds: '0' },
    { max_age_seconds: '-1' }, { max_error_rate: '1.01' }, { max_mean_abs_difference: 'NaN' }, { max_latency_ratio: '0' }]) {
    expect(() => comparisonGate({ ...draft, ...patch })).toThrow()
  }
})

test('실제 요청 입력은 JSON 배열로 파싱하고 빈 배열/객체를 거부한다', () => {
  expect(servingInputs('[[1,2,3]]')).toEqual([[1, 2, 3]])
  for (const value of ['[]', '{}', 'NaN', '']) expect(() => servingInputs(value)).toThrow()
})
