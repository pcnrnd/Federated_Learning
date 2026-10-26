import { driftScopeKey, parseDriftDraft, type DriftPolicyDraft } from '@/lib/distributionDrift'
import { LIVE_DEMO_CAPABILITY_REASON } from '@/lib/uiMode'
import { useMonitoringStore } from '@/store/useMonitoringStore'

const fields: Array<{ key: keyof DriftPolicyDraft; label: string }> = [
  { key: 'warning', label: '경고 PSI' },
  { key: 'critical', label: '경보 PSI' },
  { key: 'minimum', label: '최소 유효 표본 수' },
  { key: 'maxAge', label: '현재 관측 유효시간 (초)' },
]

interface LiveDriftPolicySectionProps {
  disabled?: boolean
}

/** 실서버 PSI 정책 필드 — demo/unconfigured에서도 동일 레이아웃 유지 */
export function LiveDriftPolicySection({ disabled = false }: LiveDriftPolicySectionProps) {
  const state = useMonitoringStore()
  const row = state.liveRows.find((value) => driftScopeKey(value) === state.selectedScope)
  const parsed = row ? parseDriftDraft(row.config_id, state.policyDraft) : null
  const locked = disabled || state.livePending

  return (
    <details className="parity-advanced-section drift-settings-panel" open={false}>
      <summary>실제 비교 정책 (PSI)</summary>
      <div className="drift-settings-body" aria-label="실제 비교 정책">
        {disabled && <p className="desc">{LIVE_DEMO_CAPABILITY_REASON}</p>}
        <div className="drift-settings-grid">
          {fields.map(({ key, label }) => (
            <div className="control-group" key={key}>
              <label htmlFor={`live-drift-${key}`}>{label}</label>
              <input
                id={`live-drift-${key}`}
                className="model-input"
                type="number"
                step={key === 'warning' || key === 'critical' ? 'any' : '1'}
                min={key === 'warning' ? 0 : undefined}
                value={state.policyDraft[key]}
                disabled={locked}
                title={disabled ? LIVE_DEMO_CAPABILITY_REASON : undefined}
                onChange={(event) => state.setPolicyDraft(key, event.target.value)}
              />
            </div>
          ))}
        </div>
        {!parsed && !disabled && (
          <p className="drift-settings-error">유한한 PSI 임계값과 1 이상의 정수 표본 수·유효시간을 입력하세요.</p>
        )}
        <button
          className="btn btn-primary"
          type="button"
          disabled={locked || !parsed || disabled}
          onClick={() => {
            void state.saveLivePolicy()
          }}
        >
          정책 저장·재조회
        </button>
        <button
          className="btn btn-secondary"
          type="button"
          disabled={
            locked ||
            disabled ||
            !row?.current_report_id ||
            Boolean(state.liveError) ||
            row?.state === 'invalid'
          }
          onClick={() => {
            void state.chooseLiveBaseline()
          }}
        >
          현재 실제 관측을 기준으로 선택
        </button>
      </div>
    </details>
  )
}
