import { useEffect } from 'react'
import { useModelStore } from '@/store/useModelStore'

interface LiveModelFormProps {
  onClose: () => void
}

export function LiveModelForm({ onClose }: LiveModelFormProps) {
  const draft = useModelStore((state) => state.liveModelDraft)
  const patch = useModelStore((state) => state.patchLiveModelDraft)
  const results = useModelStore((state) => state.liveModelResults)
  const refresh = useModelStore((state) => state.loadLiveModelResults)
  const create = useModelStore((state) => state.createLiveModel)
  const pending = useModelStore((state) => state.liveModelPending)
  const error = useModelStore((state) => state.liveModelError)
  useEffect(() => { void refresh() }, [refresh])

  return <form className="model-form glass-panel" onSubmit={(event) => {
    event.preventDefault()
    void create().then((ok) => { if (ok) onClose() })
  }}>
    <div className="control-group">
      <label htmlFor="live-model-source">등록 원본</label>
      <select id="live-model-source" value={draft.mode} disabled={pending}
        onChange={(event) => patch({ mode: event.target.value as 'training' | 'artifact' })}>
        <option value="training">완료된 실제 학습 결과</option>
        <option value="artifact">저장된 ridge artifact</option>
      </select>
    </div>
    {draft.mode === 'training' ? <div className="control-group">
      <label htmlFor="live-model-round">완료 라운드</label>
      <select id="live-model-round" value={draft.round_id} disabled={pending}
        onChange={(event) => patch({ round_id: event.target.value })}>
        <option value="">실제 결과를 선택하세요</option>
        {results.map((round) => <option key={round.round_id} value={round.round_id}>
          {round.round_id} · {round.result?.result_id}
        </option>)}
      </select>
      <button type="button" className="btn btn-secondary" disabled={pending} onClick={() => void refresh()}>결과 새로고침</button>
      {results.length === 0 && <p>등록 가능한 ridge 완료 결과가 없습니다. 정제·학습 완료 후 다시 조회하세요.</p>}
    </div> : <>
      <div className="control-group">
        <label htmlFor="live-model-name">모델 이름</label>
        <input id="live-model-name" value={draft.name} disabled={pending} onChange={(event) => patch({ name: event.target.value })} />
      </div>
      <div className="control-group">
        <label htmlFor="live-model-weights">실제 서버 artifact의 weights.json 경로</label>
        <input id="live-model-weights" value={draft.weights_path} disabled={pending}
          onChange={(event) => patch({ weights_path: event.target.value })} />
        <p>저장된 manifest·가중치·원본 결과가 모두 일치해야 등록됩니다.</p>
      </div>
    </>}
    <div className="control-group">
      <label htmlFor="live-model-version">버전 {draft.mode === 'training' ? '(선택: 비우면 서버에서 예약)' : '(필수)'}</label>
      <input id="live-model-version" value={draft.version} disabled={pending} placeholder="1.0.1"
        onChange={(event) => patch({ version: event.target.value })} />
    </div>
    {error && <p role="alert">{error}</p>}
    <div className="model-form-actions">
      <button type="button" className="btn btn-secondary" onClick={onClose} disabled={pending}>취소</button>
      <button type="submit" className="btn btn-primary" disabled={pending}>{pending ? '서버 확인 중…' : '실제 모델 등록'}</button>
    </div>
  </form>
}
