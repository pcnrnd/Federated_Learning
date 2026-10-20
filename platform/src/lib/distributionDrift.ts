import type { DistributionPolicy, DistributionPolicyInput, DriftAvailability } from '@/types/simulation'

export interface DriftPolicyDraft { warning: string; critical: string; minimum: string; maxAge: string }
export const emptyDriftDraft = (): DriftPolicyDraft => ({ warning: '', critical: '', minimum: '', maxAge: '' })
export const driftScopeKey = (scope: { config_id: string; node_id: string }): string => JSON.stringify([scope.config_id, scope.node_id])

export function draftForPolicy(policy: DistributionPolicy | null): DriftPolicyDraft {
  return policy ? { warning: String(policy.warning_threshold), critical: String(policy.critical_threshold),
    minimum: String(policy.min_valid_count), maxAge: String(policy.max_age_seconds) } : emptyDriftDraft()
}

export function parseDriftDraft(configId: string, value: DriftPolicyDraft): DistributionPolicyInput | null {
  if (Object.values(value).some((text) => text.trim() === '')) return null
  const warning = Number(value.warning), critical = Number(value.critical)
  const minimum = Number(value.minimum), maxAge = Number(value.maxAge)
  if (![warning, critical, minimum, maxAge].every(Number.isFinite) || warning < 0 || critical <= warning
    || !Number.isSafeInteger(minimum) || minimum < 1 || !Number.isSafeInteger(maxAge) || maxAge < 1) return null
  return { config_id: configId, warning_threshold: warning, critical_threshold: critical,
    min_valid_count: minimum, max_age_seconds: maxAge }
}

export const driftAvailabilityLabel: Record<DriftAvailability, string> = {
  ready: '관측 완료', unconfigured: '정책 미설정', missing_baseline: '기준 미선택',
  missing_current: '미수집', stale: '관측 유효시간 초과', invalid: '관측 불일치', insufficient: '유효 표본 부족',
}
