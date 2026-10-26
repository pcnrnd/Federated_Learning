import type { ServingGate, ServingGateDraft } from '@/types/simulation'

export function comparisonGate(draft: ServingGateDraft): ServingGate {
  const required = ['min_pairs', 'window_seconds', 'max_age_seconds', 'max_error_rate', 'max_mean_abs_difference'] as const
  if (required.some((key) => !draft[key].trim() || !Number.isFinite(Number(draft[key])))) {
    throw new Error('비교 N·구간·최신성·오류율·예측 차이 기준을 명시하세요')
  }
  const gate: ServingGate = { min_pairs: Number(draft.min_pairs), window_seconds: Number(draft.window_seconds),
    max_age_seconds: Number(draft.max_age_seconds), max_error_rate: Number(draft.max_error_rate),
    max_mean_abs_difference: Number(draft.max_mean_abs_difference),
    max_latency_ratio: draft.max_latency_ratio.trim() ? Number(draft.max_latency_ratio) : null }
  if (!Number.isInteger(gate.min_pairs) || gate.min_pairs < 1
      || !Number.isInteger(gate.window_seconds) || gate.window_seconds < 1 || gate.window_seconds > 86400
      || !Number.isInteger(gate.max_age_seconds) || gate.max_age_seconds < 1 || gate.max_age_seconds > 86400
      || gate.max_error_rate < 0 || gate.max_error_rate > 1 || gate.max_mean_abs_difference < 0
      || (gate.max_latency_ratio !== null && (!Number.isFinite(gate.max_latency_ratio) || gate.max_latency_ratio <= 0))) {
    throw new Error('비교 gate의 정수·유한 범위와 오류율(0~1)을 확인하세요')
  }
  return gate
}

export function servingInputs(text: string): unknown[] {
  const value: unknown = JSON.parse(text)
  if (!Array.isArray(value) || !value.length) throw new Error('요청 입력은 비어 있지 않은 JSON 배열이어야 합니다')
  return value
}
