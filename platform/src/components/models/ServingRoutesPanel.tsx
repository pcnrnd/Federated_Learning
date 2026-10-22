import { useEffect, useState } from 'react'
import { isLiveConfigured } from '@/api/client'
import { comparisonGate, servingInputs } from '@/lib/servingRequests'
import { useModelStore } from '@/store/useModelStore'
import { useServingStore } from '@/store/useServingStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { ServingGateDraft } from '@/types/simulation'

const LABELS: Record<keyof ServingGateDraft, string> = {
  min_pairs: '최소 동일 요청 비교 N', window_seconds: '비교 구간 (초)', max_age_seconds: '최대 관측 나이 (초)',
  max_error_rate: '최대 오류율 (0~1)', max_mean_abs_difference: '최대 평균 절대 예측 차이',
  max_latency_ratio: '최대 그림자/주 모델 지연 비율 (선택)',
}
const EMPTY: ServingGateDraft = { min_pairs: '', window_seconds: '', max_age_seconds: '',
  max_error_rate: '', max_mean_abs_difference: '', max_latency_ratio: '' }
const metric = (value: number | null | undefined) => value == null ? '미측정' : value.toFixed(3)

export function ServingRoutesPanel() {
  const state = useServingStore()
  const deployments = useModelStore((s) => s.deployments)
  const mock = useSimulationStore((s) => s.mockEnabled)
  const [primary, setPrimary] = useState('')
  const [version, setVersion] = useState('')
  const [mirror, setMirror] = useState(100)
  const [gateDraft, setGateDraft] = useState<ServingGateDraft>(EMPTY)
  const [inputText, setInputText] = useState('')
  const [draftError, setDraftError] = useState<string | null>(null)
  const live = !mock && isLiveConfigured()
  const route = state.routes.find((value) => value.route_id === state.selected)
  useEffect(() => {
    if (!live) return
    void useServingStore.getState().poll()
    const timer = window.setInterval(() => { void useServingStore.getState().poll() }, 4000)
    return () => window.clearInterval(timer)
  }, [live])
  const submitGate = () => {
    try { void state.gate(comparisonGate(gateDraft)); setDraftError(null) }
    catch (error) { setDraftError(error instanceof Error ? error.message : '비교 기준을 확인하세요') }
  }
  const predict = () => {
    try { const inputs = servingInputs(inputText); setInputText(''); setDraftError(null); void state.predict(inputs) }
    catch { setDraftError('요청 입력은 비어 있지 않은 JSON 배열이어야 합니다') }
  }
  const loadGate = () => {
    if (!route?.comparison_gate) return
    const gate = route.comparison_gate
    setGateDraft(Object.fromEntries(Object.keys(EMPTY).map((key) => {
      const value = gate[key as keyof typeof gate]
      return [key, value === null ? '' : String(value)]
    })) as unknown as ServingGateDraft)
  }
  const head = <div className="deploy-card-head">
    <h4><i className="fa-solid fa-route" /> 실제 요청 경로·그림자 비교</h4>
  </div>
  if (!live) return <div className="deploy-card glass-panel serving-routes-panel">{head}
    <div className="deploy-empty">실서버 데이터 조회 상태에서 요청 경로를 연결하고 관측할 수 있습니다.</div></div>
  return <div className="deploy-card glass-panel serving-routes-panel">
    {head}
    {(state.error || draftError) && <p role="alert" className="text-red">{draftError ?? state.error}</p>}
    <div className="serving-routes-row">
      <div className="control-group">
        <label htmlFor="serving-primary">실제 검증된 주 실행</label>
        <select id="serving-primary" className="model-input" value={primary} onChange={(event) => setPrimary(event.target.value)}>
          <option value="">선택하세요</option>
          {deployments.filter((value) => !value.isSchedule && value.state === 'done' && value.verifiedAt).map((value) =>
            <option key={value.id} value={value.id}>{value.modelLabel} · {value.id}</option>)}
        </select>
      </div>
      <button type="button" className="model-action deploy" disabled={!primary || state.pending}
        onClick={() => { void state.create(primary) }}>요청 경로 연결</button>
    </div>
    <div className="control-group">
      <label htmlFor="serving-route">요청 경로</label>
      <select id="serving-route" aria-label="요청 경로" className="model-input" value={state.selected ?? ''}
        onChange={(event) => state.select(event.target.value)}>
        <option value="">경로 선택</option>
        {state.routes.map((value) => <option key={value.route_id} value={value.route_id}>{value.route_id} · {value.status}</option>)}
      </select>
    </div>
    {route && <>
      <p className="desc">요청 주소: <code>/api/serving-routes/{route.route_id}/predict</code></p>
      <p className="desc">주 실행 {route.primary_deployment_id} · 그림자 {route.shadow_deployment_id ?? '없음'} · 복원용 대기 실행 {route.previous_deployment_id ?? '없음'}</p>
      <p className="desc">대기 실행은 복원용으로 유지됩니다. 경로 종료 후 정리 확인 전까지 실행 참조를 보존합니다.</p>
      <div className="serving-routes-row">
        <input aria-label="그림자 모델 버전" className="model-input" value={version} placeholder="실제 등록된 비교 버전"
          onChange={(event) => setVersion(event.target.value)} />
        <input aria-label="그림자 전송 비율" className="model-input serving-routes-ratio" type="number" min={0} max={100} value={mirror}
          onChange={(event) => setMirror(Number(event.target.value))} />
        <button type="button" className="model-action deploy" disabled={state.pending || !version.trim() || !!route.shadow_id || route.status === 'closed'
          || !Number.isFinite(mirror) || mirror < 0 || mirror > 100} onClick={() => { void state.shadow(version.trim(), mirror) }}>실제 그림자 연결</button>
      </div>
      <details className="drift-settings-panel parity-advanced-section">
        <summary className="drift-settings-header">
          <span className="drift-settings-title"><i className="fa-solid fa-sliders" /> 명시적 비교·승격 기준</span>
          <i className="fa-solid fa-chevron-down drift-settings-chevron" aria-hidden="true" />
        </summary>
        <div className="drift-settings-body">
          <button type="button" className="model-action" disabled={!route.comparison_gate} onClick={loadGate}>서버 기준 불러오기</button>
          {(Object.keys(LABELS) as Array<keyof ServingGateDraft>).map((key) => <label key={key} className="control-group">
            {LABELS[key]}<input className="model-input" type="number" value={gateDraft[key]}
              onChange={(event) => setGateDraft((draft) => ({ ...draft, [key]: event.target.value }))} />
          </label>)}
          <button type="button" className="model-action deploy" disabled={state.pending || !route.shadow_deployment_id} onClick={submitGate}>기준 저장·새 비교 구간 시작</button>
        </div>
      </details>
      <textarea aria-label="일시적 예측 확인 입력" className="model-input" value={inputText}
        onChange={(event) => setInputText(event.target.value)} placeholder="JSON 입력 배열" />
      <div className="serving-routes-actions">
        <button type="button" className="model-action deploy" disabled={state.pending || route.status === 'closed' || !inputText.trim()} onClick={predict}>실제 요청 전송</button>
      </div>
      <p className="desc">입력·예측 값은 저장하지 않습니다. 예측 차이는 정확도 지표가 아닙니다.</p>
      {state.lastResponse && <p className="desc">요청 {state.lastResponse.request_id} · 실제 응답 버전 {state.lastResponse.version} · 입력 {state.lastResponse.input_count}건</p>}
      {state.comparison && <>
        <p>구간 {state.comparison.window_start} ~ {state.comparison.window_end} · 동일 요청 비교 N={state.comparison.pairs}
          · 예측 차이 평균 {metric(state.comparison.mean_abs_difference)} · 진행 {state.comparison.pending} · 재시작 중단 {state.comparison.interrupted}</p>
        <ul>{Object.entries(state.comparison.roles).map(([role, value]) => <li key={role}>
          {role === 'primary' ? '주 모델' : '그림자'}: 요청 {value.requests} · 성공 {value.successes} · 오류 {value.errors}
          · 지연 {metric(value.mean_latency_ms)}ms · 완료 {value.completed_requests ?? value.successes + value.errors}건
          · 완료 시각 창 처리량 {metric(value.throughput_rps)}요청/초
          · 동일 요청 지연 {metric(state.comparison?.paired_roles[role]?.mean_latency_ms)}ms
        </li>)}</ul>
        <p>{state.comparison.gate_ready ? '관측 기준 충족 · 승격 시 현재 건강 상태를 다시 확인합니다' : state.comparison.gate_reasons.join(' · ')}</p>
      </>}
      <div className="serving-routes-actions">
        <button type="button" className="model-action deploy" disabled={state.pending || !state.comparison?.gate_ready} onClick={() => { void state.action('promote') }}>실제 요청 경로 승격</button>
        <button type="button" className="model-action rollback" disabled={state.pending || route.status !== 'promoted'} onClick={() => { void state.action('rollback') }}>이전 정상 경로 복원</button>
        <button type="button" className="model-action remove" disabled={state.pending || route.status === 'closed'} onClick={() => { void state.action('close') }}>경로 종료·정리</button>
        {route.cleanup_pending && <button type="button" className="model-action" disabled={state.pending} onClick={() => { void state.action('cleanup') }}>미확인 정리 재시도</button>}
      </div>
      {route.error && <p role="alert" className="text-red">{route.error}</p>}
      <ul>{state.shadows.filter((value) => value.route_id === route.route_id).map((value) => <li key={value.shadow_id}>
        그림자 {value.shadow_version}: {value.status} {value.error}
        {(value.status === 'failed' || value.status === 'initializing') && !value.cleanup_pending && <button type="button" disabled={state.pending}
          onClick={() => { void state.shadowAction(value.shadow_id, 'retry') }}>동일 기동 재시도</button>}
        {['active', 'initializing', 'failed'].includes(value.status) && <button type="button" disabled={state.pending}
          onClick={() => { void state.shadowAction(value.shadow_id, 'abort') }}>{value.cleanup_pending ? '그림자 정리 재시도' : '그림자 중단'}</button>}
      </li>)}</ul>
      <details><summary>실제 요청·오류 메타 기록</summary><ul>{state.events.map((event) => <li key={event.request_id}>
        {event.request_id} · {event.status} · {event.started_at} · {Object.entries(event.roles).map(([role, value]) =>
          `${role}: ${value.version}/${value.status}/${metric(value.duration_ms)}ms/${value.error_code ?? '오류 없음'}`).join(' · ')}
      </li>)}</ul></details>
    </>}
  </div>
}
