import { isLiveConfigured } from '@/api/client'
import { driftAvailabilityLabel, driftScopeKey, parseDriftDraft, type DriftPolicyDraft } from '@/lib/distributionDrift'
import { useMonitoringStore } from '@/store/useMonitoringStore'
import type { DriftObservation } from '@/types/simulation'

const severityLabel = { stable: '정상', warning: '주의', critical: '임계 초과' }
const statusLabel = { open: '미확인', acked: '확인함', resolved: '해소됨' }
const count = (value: number | null) => value === null ? '미수집' : String(value)

interface ObservationProps { row: DriftObservation; unavailable?: boolean }

function DistributionCounts({ row, unavailable }: ObservationProps) {
  if (unavailable || row.state !== 'ready' || !row.baseline_bin_counts || !row.current_bin_counts) return null
  return <div className="model-table-wrapper"><table className="model-table">
    <caption>공통 구간별 실제 유효 표본 수 (범위 밖 값은 양 끝 구간에 포함)</caption>
    <thead><tr><th>구간</th><th>기준</th><th>현재</th></tr></thead>
    <tbody>{row.current_bin_counts.map((value, index) => <tr key={index}>
      <td>{index === 0 ? '−∞' : row.bin_edges[index]} ≤ 값 {index === row.current_bin_counts!.length - 1 ? '≤' : '<'} {index === row.current_bin_counts!.length - 1 ? '+∞' : row.bin_edges[index + 1]}</td>
      <td>{row.baseline_bin_counts![index]}</td><td>{value}</td>
    </tr>)}</tbody>
  </table></div>
}

function Observation({ row, unavailable }: ObservationProps) {
  const label = unavailable ? '갱신 실패 · 현재 판단 불가' : row.state === 'ready' && row.severity ? severityLabel[row.severity] : driftAvailabilityLabel[row.state]
  const level = unavailable || row.state !== 'ready' ? 'warn' : row.severity === 'stable' ? 'ok' : row.severity === 'critical' ? 'alert' : 'warn'
  return <>
    <h4>{row.model_name}@{row.version} · {row.node_id} · {row.feature}</h4>
    <p role={row.state !== 'ready' || row.severity !== 'stable' ? 'status' : undefined}>
      <strong className={`drift-badge drift-badge-${level}`}>{label}</strong> · PSI {unavailable || row.psi === null ? '계산할 수 없음' : row.psi.toFixed(6)}
    </p>
    <p>{row.reason}</p>
    <p>기준 시점: {row.baseline_at ?? '미선택'}<br />현재 시점: {row.current_at ?? '미수집'}</p>
    <p>기준 N {count(row.baseline_total_count)} / 유효 {count(row.baseline_valid_count)} / 제외 {count(row.baseline_excluded_count)}<br />
      현재 N {count(row.current_total_count)} / 유효 {count(row.current_valid_count)} / 제외 {count(row.current_excluded_count)}</p>
    <p>기준 관측 창: {row.baseline_window_start ?? '없음'} ~ {row.baseline_window_end ?? '없음'}<br />
      현재 관측 창: {row.window_start ?? '없음'} ~ {row.window_end ?? '없음'}</p>
    <p>적용 정책: {row.policy ? `v${row.policy.policy_version} · 경고 PSI ${row.policy.warning_threshold} / 경보 PSI ${row.policy.critical_threshold}` : '미설정'}</p>
    <details><summary>관측 계보</summary><p style={{ overflowWrap: 'anywhere' }}>
      분포 설정: {row.config_id}<br />정책: {row.policy?.policy_id ?? '없음'}<br />
      기준: {row.baseline_report_id ?? '없음'}<br />현재: {row.current_report_id ?? '없음'}<br />비교: {row.event_id}
    </p></details>
    <DistributionCounts row={row} unavailable={unavailable} />
  </>
}

function DriftAlerts({ row }: ObservationProps) {
  const alerts = useMonitoringStore((state) => state.liveAlerts)
  const pending = useMonitoringStore((state) => state.livePending)
  const ack = useMonitoringStore((state) => state.ackLiveAlert)
  const matching = alerts.filter((alert) => alert.config_id === row.config_id && alert.node_id === row.node_id)
  return <div aria-label="실제 분포 경고">
    <h4>경고와 해소 이력</h4>
    <p>확인은 경고를 읽었다는 뜻입니다. 해소는 적용 기준·정책에 따른 유효한 정상 비교가 확인된 경우에 기록됩니다.</p>
    {!matching.length && <p>이 대상의 경고가 없습니다.</p>}
    {matching.map((alert) => <div key={alert.alert_id} className="glass-panel content-card">
      <p><strong>{statusLabel[alert.status]}</strong> · {severityLabel[alert.severity]} · 정책 v{alert.policy_version}</p>
      <p>{alert.message} · {alert.node_id} · {alert.feature}</p>
      <p>발생 {alert.triggered_at}{alert.acked_at && ` / 확인 ${alert.acked_at}`}{alert.resolved_at && ` / 해소 ${alert.resolved_at}`}</p>
      <details><summary>경고 계보</summary><p style={{ overflowWrap: 'anywhere' }}>
        관측 {alert.event_id}<br />해소 관측 {alert.resolved_by_event_id ?? '없음'}</p></details>
      {alert.status === 'open' && <button className="btn btn-secondary" disabled={pending}
        onClick={() => { void ack(alert.alert_id) }}>확인</button>}
    </div>)}
  </div>
}

export function LiveDriftCard() {
  const state = useMonitoringStore()
  if (!isLiveConfigured()) return <div className="deploy-empty">실제 분포 API가 설정되지 않았습니다.</div>
  const row = state.liveRows.find((value) => driftScopeKey(value) === state.selectedScope)
  return <section className="glass-panel content-card" aria-label="실제 데이터 드리프트">
    <h3>실제 데이터 드리프트</h3>
    <p>원시 값 없이 검증된 정제 출력의 공통 히스토그램을 비교합니다. PSI는 백분율이 아닙니다.</p>
    <button className="btn btn-secondary" disabled={state.livePending || state.pollPending}
      onClick={() => { void state.pollLive() }}>새로고침</button>
    {state.liveError && <p role="alert">갱신 실패: {state.liveError} — 아래 내용은 마지막 성공 조회값입니다.</p>}
    {state.pollPending && <p role="status">관측 조회 중…</p>}
    {!state.liveRows.length ? <p>수집 설정 또는 실제 관측이 없습니다. 아직 정상 여부를 판단할 수 없습니다.</p> : <>
      <label htmlFor="live-drift-scope">모델 · 특성 · 사일로</label>
      <select id="live-drift-scope" className="model-input" value={state.selectedScope ?? ''} disabled={state.livePending}
        onChange={(event) => state.selectLiveScope(event.target.value)}>
        {state.liveRows.map((value) => <option key={driftScopeKey(value)} value={driftScopeKey(value)}>
          {value.model_name}@{value.version} · {value.feature} · {value.node_id} · {value.config_id.slice(0, 8)}
        </option>)}
      </select>
      {row && <><Observation row={row} unavailable={Boolean(state.liveError)} /><DriftAlerts row={row} /></>}
    </>}
  </section>
}

const fields: Array<{ key: keyof DriftPolicyDraft; label: string }> = [
  { key: 'warning', label: '경고 PSI' }, { key: 'critical', label: '경보 PSI' },
  { key: 'minimum', label: '최소 유효 표본 수' }, { key: 'maxAge', label: '현재 관측 유효시간 (초)' },
]

export function LiveDriftSettings() {
  const state = useMonitoringStore()
  const row = state.liveRows.find((value) => driftScopeKey(value) === state.selectedScope)
  if (!row) return null
  const parsed = parseDriftDraft(row.config_id, state.policyDraft)
  return <section className="drift-settings-panel" aria-label="실제 비교 정책">
    <div className="drift-settings-body">
      <h4>서버 비교 정책과 기준 선택</h4>
      <p>경고 PSI &lt; 경보 PSI. 설정은 선택한 공통 분포 설정의 모든 사일로에 적용됩니다.</p>
      <div className="drift-settings-grid">{fields.map(({ key, label }) => <div className="control-group" key={key}>
        <label htmlFor={`live-drift-${key}`}>{label}</label>
        <input id={`live-drift-${key}`} className="model-input" type="number" step={key === 'warning' || key === 'critical' ? 'any' : '1'}
          min={key === 'warning' ? 0 : undefined} value={state.policyDraft[key]} disabled={state.livePending}
          onChange={(event) => state.setPolicyDraft(key, event.target.value)} />
      </div>)}</div>
      {!parsed && <p className="drift-settings-error">유한한 PSI 임계값과 1 이상의 정수 표본 수·유효시간을 입력하세요.</p>}
      <button className="btn btn-primary" disabled={!parsed || state.livePending} onClick={() => { void state.saveLivePolicy() }}>정책 저장·재조회</button>
      <p>기준은 명시적으로 선택한 실제 관측이며 새 관측으로 자동 교체되지 않습니다.</p>
      <button className="btn btn-secondary" disabled={!row.current_report_id || state.livePending || Boolean(state.liveError) || row.state === 'invalid'}
        onClick={() => { void state.chooseLiveBaseline() }}>현재 실제 관측을 기준으로 선택</button>
    </div>
  </section>
}
