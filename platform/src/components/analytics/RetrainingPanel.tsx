import { useEffect } from 'react'
import { isLiveConfigured } from '@/api/client'
import { DEMO_RETRAINING_REASON, resolveUiDataMode, UNCONFIGURED_API_MESSAGE } from '@/lib/uiMode'
import { retrainingError, retrainingPayload, retrainingStatus } from '@/lib/retraining'
import { useRetrainingStore } from '@/store/useRetrainingStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { RetrainingEvent } from '@/types/simulation'
import { RetrainingLineage } from './RetrainingLineage'

interface EventProps {
  event: RetrainingEvent
}

function EventCard({ event }: EventProps) {
  const pending = useRetrainingStore((s) => s.pending)
  const retry = useRetrainingStore((s) => s.retry)
  const error = retrainingError(event.error_code)
  return (
    <article className="glass-panel content-card">
      <strong>{retrainingStatus[event.status] ?? '상태 확인 필요'}</strong>
      <p>
        {event.training_request.model_name}@{event.training_request.version} ·{' '}
        {event.automatic ? '자동 요청' : '수동 요청'} · {event.updated_at}
      </p>
      {error && <p role="alert">{error}</p>}
      {event.registered_model && (
        <p>
          새 실험 모델 {event.registered_model.name}@{event.registered_model.version} 등록 완료. 운영 전환은
          별도입니다.
        </p>
      )}
      {event.status === 'failed' && (
        <button className="btn btn-secondary" disabled={pending} onClick={() => void retry(event.event_id)}>
          같은 실행 다시 확인
        </button>
      )}
      <RetrainingLineage event={event} />
    </article>
  )
}

export function RetrainingPanel() {
  const mock = useSimulationStore((s) => s.mockEnabled)
  const mode = resolveUiDataMode(mock)
  const observe = useRetrainingStore((s) => s.observe)
  const state = useRetrainingStore()

  useEffect(() => {
    if (mode === 'live') return observe()
  }, [mode, observe])

  const capabilityLocked = mode !== 'live' || !isLiveConfigured()
  const lockReason = mode === 'demo' ? DEMO_RETRAINING_REASON : UNCONFIGURED_API_MESSAGE
  const parsed = retrainingPayload(state.draft, state.snapshot.options)
  const selected = state.snapshot.configs.find((c) => c.retrain_config_id === state.selected)
  const disabled = capabilityLocked || state.pending || state.polling

  return (
    <section className="glass-panel content-card" aria-label="실제 재교육">
      <h3>데이터 정제·재학습</h3>
      <p>저장한 기준 모델과 같은 학습 항목으로 다시 학습합니다. 경고 확인·해소와 새 모델 등록은 별도입니다.</p>
      {capabilityLocked && (
        <p className="deploy-empty" role="status">
          {lockReason}
        </p>
      )}
      {state.command && (
        <p role="status">
          서버 확인이 끝나지 않은 재교육 요청이 있습니다.{' '}
          <button type="button" className="btn btn-secondary" disabled={disabled} onClick={() => void state.resumeCommand()}>
            이전 요청 확인
          </button>
        </p>
      )}
      {state.error && <p role="alert">조회·요청 실패: {state.error}. 표시 내용은 마지막 성공 조회값입니다.</p>}
      {selected?.error_code && (
        <p role="alert">자동 재교육 대기: {retrainingError(selected.error_code)}</p>
      )}
      <button className="btn btn-secondary" type="button" disabled={disabled} onClick={() => void state.poll()}>
        상태 새로고침
      </button>
      <label htmlFor="retrain-config-select">
        저장된 재교육 설정
        <select
          id="retrain-config-select"
          className="model-input"
          value={state.selected ?? ''}
          disabled={disabled}
          onChange={(e) => state.select(e.target.value)}
        >
          <option value="">새 설정</option>
          {state.snapshot.configs.map((c) => (
            <option key={c.retrain_config_id} value={c.retrain_config_id}>
              {c.definition.model_name}@{c.definition.version} · 설정 v{c.config_version}
            </option>
          ))}
        </select>
      </label>
      <label htmlFor="retrain-baseline-select">
        기준 모델·분포
        <select
          id="retrain-baseline-select"
          className="model-input"
          value={state.draft.configId}
          disabled={disabled}
          onChange={(e) => state.patch({ configId: e.target.value })}
        >
          <option value="">선택하세요</option>
          {state.snapshot.options.map((o) => (
            <option key={o.config_id} value={o.config_id}>
              {o.model_name}@{o.version} · {o.feature}
              {o.policy_id ? '' : ' (비교 정책 필요)'}
            </option>
          ))}
        </select>
      </label>
      <label htmlFor="retrain-group-select">
        참여 그룹
        <select
          id="retrain-group-select"
          className="model-input"
          value={state.draft.groupId}
          disabled={disabled}
          onChange={(e) => state.patch({ groupId: e.target.value })}
        >
          <option value="">선택하세요</option>
          {state.snapshot.groups.map((g) => (
            <option key={g.group_id} value={g.group_id}>
              {g.group_id} · 대표 {g.members}곳
            </option>
          ))}
        </select>
      </label>
      <label htmlFor="retrain-dataset-input">
        사일로 데이터셋
        <input
          id="retrain-dataset-input"
          className="model-input"
          value={state.draft.dataset}
          disabled={disabled}
          onChange={(e) => state.patch({ dataset: e.target.value })}
        />
      </label>
      <label htmlFor="retrain-rounds-input">
        학습 라운드
        <input
          id="retrain-rounds-input"
          className="model-input"
          type="number"
          min={2}
          max={100}
          value={state.draft.rounds}
          disabled={disabled}
          onChange={(e) => state.patch({ rounds: e.target.value })}
        />
      </label>
      <label htmlFor="retrain-enabled-checkbox">
        <input
          id="retrain-enabled-checkbox"
          type="checkbox"
          checked={state.draft.enabled}
          disabled={disabled}
          onChange={(e) => state.patch({ enabled: e.target.checked })}
        />{' '}
        설정 사용
      </label>
      <label htmlFor="retrain-automatic-checkbox">
        <input
          id="retrain-automatic-checkbox"
          type="checkbox"
          checked={state.draft.automatic}
          disabled={disabled}
          onChange={(e) => state.patch({ automatic: e.target.checked })}
        />{' '}
        유효한 경보에서 자동 재교육 요청
      </label>
      <button className="btn btn-primary" type="button" disabled={disabled || !parsed} onClick={() => void state.save()}>
        설정 저장
      </button>{' '}
      <button
        className="btn btn-primary"
        type="button"
        disabled={disabled || state.dirty || !selected?.definition.enabled}
        onClick={() => void state.run()}
      >
        저장한 설정으로 재교육
      </button>
      {!state.snapshot.events.length && <p>재교육 실행 이력이 없습니다.</p>}
      {state.snapshot.events.map((event) => (
        <EventCard key={event.event_id} event={event} />
      ))}
    </section>
  )
}
