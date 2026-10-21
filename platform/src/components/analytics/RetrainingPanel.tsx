import { useEffect } from 'react'
import { isLiveConfigured } from '@/api/client'
import { DEMO_RETRAINING_REASON, resolveUiDataMode } from '@/lib/uiMode'
import { retrainingError, retrainingPayload, retrainingStatus } from '@/lib/retraining'
import { useRetrainingStore } from '@/store/useRetrainingStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { RetrainingEvent } from '@/types/simulation'
import { RetrainingLineage } from './RetrainingLineage'

interface EventProps { event: RetrainingEvent }

function EventCard({ event }: EventProps) {
  const pending = useRetrainingStore((s) => s.pending)
  const retry = useRetrainingStore((s) => s.retry)
  const error = retrainingError(event.error_code)
  return <article className="glass-panel content-card">
    <strong>{retrainingStatus[event.status] ?? '상태 확인 필요'}</strong>
    <p>{event.training_request.model_name}@{event.training_request.version} · {event.automatic ? '자동 요청' : '수동 요청'} · {event.updated_at}</p>
    {error && <p role="alert">{error}</p>}
    {event.registered_model && <p>새 실험 모델 {event.registered_model.name}@{event.registered_model.version} 등록 완료. 운영 전환은 별도입니다.</p>}
    {event.status === 'failed' && <button className="btn btn-secondary" disabled={pending} onClick={() => { void retry(event.event_id) }}>같은 실행 다시 확인</button>}
    <RetrainingLineage event={event} />
  </article>
}

export function RetrainingPanel() {
  const mock = useSimulationStore((s) => s.mockEnabled)
  const mode = resolveUiDataMode(mock)
  const observe = useRetrainingStore((s) => s.observe)
  const state = useRetrainingStore()
  useEffect(() => {
    if (mode === 'live') return observe()
  }, [mode, observe])
  if (mode === 'demo') {
    return (
      <section className="glass-panel content-card" aria-label="실제 재교육">
        <h3>데이터 정제·재학습</h3>
        <p className="deploy-empty" role="status">
          {DEMO_RETRAINING_REASON}
        </p>
      </section>
    )
  }
  if (!isLiveConfigured()) {
    return (
      <section className="glass-panel content-card" aria-label="실제 재교육">
        <h3>데이터 정제·재학습</h3>
        <p className="deploy-empty" role="status">
          실데이터 API 주소 설정 후 재교육 기능을 사용할 수 있습니다.
        </p>
      </section>
    )
  }
  const parsed = retrainingPayload(state.draft, state.snapshot.options)
  const selected = state.snapshot.configs.find((c) => c.retrain_config_id === state.selected)
  const disabled = state.pending || state.polling
  return <section className="glass-panel content-card" aria-label="실제 재교육">
    <h3>데이터 정제·재학습</h3>
    <p>저장한 기준 모델과 같은 학습 항목으로 다시 학습합니다. 경고 확인·해소와 새 모델 등록은 별도입니다.</p>
    {state.command && <p role="status">서버 확인이 끝나지 않은 재교육 요청이 있습니다. 새 요청을 만들기 전에 이전 요청을 확인하세요.{' '}
      <button type="button" className="btn btn-secondary" disabled={disabled} onClick={() => { void state.resumeCommand() }}>이전 요청 확인</button></p>}
    {state.error && <p role="alert">조회·요청 실패: {state.error}. 표시 내용은 마지막 성공 조회값입니다.</p>}
    {selected?.error_code && <p role="alert">자동 재교육 대기: {retrainingError(selected.error_code)}</p>}
    <button className="btn btn-secondary" disabled={disabled} onClick={() => { void state.poll() }}>상태 새로고침</button>
    <label>저장된 재교육 설정<select className="model-input" value={state.selected ?? ''} disabled={disabled}
      onChange={(e) => state.select(e.target.value)}><option value="">새 설정</option>
      {state.snapshot.configs.map((c) => <option key={c.retrain_config_id} value={c.retrain_config_id}>{c.definition.model_name}@{c.definition.version} · 설정 v{c.config_version}</option>)}
    </select></label>
    <label>기준 모델·분포<select className="model-input" value={state.draft.configId} disabled={disabled}
      onChange={(e) => state.patch({ configId: e.target.value })}><option value="">선택하세요</option>
      {state.snapshot.options.map((o) => <option key={o.config_id} value={o.config_id}>{o.model_name}@{o.version} · {o.feature}{o.policy_id ? '' : ' (비교 정책 필요)'}</option>)}
    </select></label>
    <label>참여 그룹<select className="model-input" value={state.draft.groupId} disabled={disabled}
      onChange={(e) => state.patch({ groupId: e.target.value })}><option value="">선택하세요</option>
      {state.snapshot.groups.map((g) => <option key={g.group_id} value={g.group_id}>{g.group_id} · 대표 {g.members}곳</option>)}
    </select></label>
    <label>사일로 데이터셋<input className="model-input" value={state.draft.dataset} disabled={disabled}
      onChange={(e) => state.patch({ dataset: e.target.value })} /></label>
    <label>학습 라운드<input className="model-input" type="number" min={2} max={100} value={state.draft.rounds} disabled={disabled}
      onChange={(e) => state.patch({ rounds: e.target.value })} /></label>
    <label><input type="checkbox" checked={state.draft.enabled} disabled={disabled} onChange={(e) => state.patch({ enabled: e.target.checked })} /> 설정 사용</label>
    <label><input type="checkbox" checked={state.draft.automatic} disabled={disabled} onChange={(e) => state.patch({ automatic: e.target.checked })} /> 유효한 경보에서 자동 재교육 요청</label>
    <p>실제 ridge 가중치, 같은 정제 규칙과 참여 범위를 확인한 설정만 저장할 수 있습니다. 자동 실행은 이 선택을 저장한 이후 적용됩니다.</p>
    <button className="btn btn-primary" disabled={disabled || !parsed} onClick={() => { void state.save() }}>설정 저장</button>{' '}
    <button className="btn btn-primary" disabled={disabled || state.dirty || !selected?.definition.enabled} onClick={() => { void state.run() }}>저장한 설정으로 재교육</button>
    {!state.snapshot.events.length && <p>재교육 실행 이력이 없습니다.</p>}
    {state.snapshot.events.map((event) => <EventCard key={event.event_id} event={event} />)}
  </section>
}
