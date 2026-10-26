import { expect, test } from 'vitest'
import { emptyRetrainingDraft, retrainingError, retrainingPayload, retrainingStatus } from './retraining'

const options = [{ config_id: 'a'.repeat(64), policy_id: 'b'.repeat(64), model_name: '실제 모델', version: '1.0.0', feature: 'x' }]
const valid = () => ({ ...emptyRetrainingDraft(), configId: options[0].config_id, groupId: 'group', dataset: 'patients_2026', rounds: '2' })

test('저장된 정책과 명시적 자동 opt-in을 실제 설정 요청에 반영한다', () => {
  expect(retrainingPayload(valid(), options)).toEqual({ config_id: options[0].config_id, policy_id: options[0].policy_id,
    group_id: 'group', dataset_label: 'patients_2026', max_rounds: 2, enabled: true, auto_enabled: false })
  expect(retrainingPayload({ ...valid(), automatic: true }, options)?.auto_enabled).toBe(true)
})

test.each(['1', '0', '101', 'NaN', '2.5', ''])('global feedback 없는/유효하지 않은 라운드 %s를 거부한다', (rounds) => {
  expect(retrainingPayload({ ...valid(), rounds }, options)).toBeNull()
})

test('정책 부재와 경로/원시 입력은 실행 설정이 되지 않는다', () => {
  expect(retrainingPayload(valid(), [{ ...options[0], policy_id: null }])).toBeNull()
  for (const dataset of ['../raw', '/data/raw', 'secret\nrow', '']) expect(retrainingPayload({ ...valid(), dataset }, options)).toBeNull()
  expect(retrainingError('HTTP_503')).toContain('보존')
  expect(retrainingStatus.registered).toBe('새 모델 등록 완료')
})
