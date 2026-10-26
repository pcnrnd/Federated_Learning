import { expect, test } from 'vitest'
import { draftForPolicy, driftScopeKey, emptyDriftDraft, parseDriftDraft } from './distributionDrift'

test('PSI를 백분율로 제한하지 않고 저장할 실제 정책 값을 만든다', () => {
  expect(parseDriftDraft('config', { warning: '1.3', critical: '2.7', minimum: '12', maxAge: '90' })).toEqual({
    config_id: 'config', warning_threshold: 1.3, critical_threshold: 2.7, min_valid_count: 12, max_age_seconds: 90,
  })
  expect(draftForPolicy(null)).toEqual(emptyDriftDraft())
})

test.each([
  { warning: '', critical: '1', minimum: '1', maxAge: '1' },
  { warning: 'NaN', critical: '1', minimum: '1', maxAge: '1' },
  { warning: '0.1', critical: 'Infinity', minimum: '1', maxAge: '1' },
  { warning: '0.1', critical: '0.1', minimum: '1', maxAge: '1' },
  { warning: '-1', critical: '1', minimum: '1', maxAge: '1' },
  { warning: '0.1', critical: '1', minimum: '0', maxAge: '1' },
  { warning: '0.1', critical: '1', minimum: '1.5', maxAge: '1' },
  { warning: '0.1', critical: '1', minimum: '1', maxAge: '0' },
])('빈값·무한대·잘못된 경계는 정상 정책으로 채우지 않는다: %j', (draft) => {
  expect(parseDriftDraft('config', draft)).toBeNull()
})

test('사일로 원래 식별자와 두 구성요소의 경계를 보존한다', () => {
  expect(driftScopeKey({ config_id: 'c', node_id: 'silo-01' })).not.toBe(driftScopeKey({ config_id: 'c', node_id: 'silo-1' }))
  expect(driftScopeKey({ config_id: 'a/b', node_id: 'c' })).not.toBe(driftScopeKey({ config_id: 'a', node_id: 'b/c' }))
})
