import { describe, expect, test } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { LiveRoundResult, liveTrainingRequest } from './LiveTrainingScheduler'
import type { TrainingRoundSummary } from '@/api/client'

const draft = { job_id: 'learn', model_name: 'm', version: '1.0.0', group_id: 'root', cleaning_job_id: 'cleaned',
  features: 'x1, x2,x3', target: 'y', initial: '1,2,3,4', l2: '0.001', step_size: '0.0001', steps: '1',
  max_rounds: '2', min_contributions: '2' }

describe('실제 연속 학습 계약', () => {
  test('정제 작업과 명시 초기 모델/solver 설정을 같은 서버 작업으로 전달한다', () => {
    const payload = liveTrainingRequest(draft)
    expect(payload.cleaning_job_id).toBe('cleaned')
    expect(payload.schedule_kind).toBe('chain')
    expect(payload.min_contributions).toBe(2)
    expect(payload.learning).toEqual({ solver: 'ridge_gradient_v1', features: ['x1', 'x2', 'x3'], target: 'y',
      initial_parameters: [1, 2, 3, 4], l2: 0.001, step_size: 0.0001, steps: 1 })
  })
  test.each(['0,,0,0', '0,NaN,0,0', '0,0', '0,Infinity,0,0'])('빈/비유한/차원불일치 초기값 거부: %s', (initial) => {
    expect(() => liveTrainingRequest({ ...draft, initial })).toThrow()
  })
  test('완료 응답의 저장된 result/checksum/파라미터를 그대로 표시하고 빈 값을 0으로 채우지 않는다', () => {
    const round: TrainingRoundSummary = { round_id: 'r', status: 'completed', contributors: ['silo-1'], total_samples: 3,
      result: { result_id: 'result-1', checksum: 'checksum-1', parameters: [1, 2, 3, 4], parameter_dim: 4,
        total_samples: 3, format: 'ridge-v1', features: ['x1', 'x2', 'x3'], target: 'y' } }
    const html = renderToStaticMarkup(<LiveRoundResult round={round} />)
    expect(html).toContain('result-1')
    expect(html).toContain('checksum-1')
    expect(html).toContain('[1, 2, 3, 4]')
    const historical = renderToStaticMarkup(<LiveRoundResult round={{ ...round, result: null }} />)
    expect(historical).toContain('과거 결과 파라미터 미보존')
    expect(historical).not.toContain('[0')
    expect(renderToStaticMarkup(<LiveRoundResult round={{ ...round, status: 'aggregating', result: null }} />)).toContain('결과 준비 중')
  })
})
