import { useDataStore } from '@/store/useDataStore'
import { useSiloStore } from '@/store/useSiloStore'

const FIELDS = [
  ['job_id', '작업 ID', 'text'], ['recipe_name', '등록 레시피 이름', 'text'],
  ['recipe_version', '레시피 버전', 'text'], ['dataset_label', '로컬 데이터셋', 'text'],
  ['scheduled_at', '최초 실행 시각 (빈 값: 즉시)', 'datetime-local'],
  ['interval_seconds', '반복 주기 (초, 빈 값: 1회)', 'number'],
  ['max_occurrences', '최대 회차 (빈 값: 계속)', 'number'],
  ['depends_on', '선행 정제 ID (쉼표로 구분)', 'text'],
  ['max_attempts', '최대 시도 수', 'number'], ['retry_backoff_seconds', '재시도 대기 (초)', 'number'],
  ['timeout_seconds', '시도 시간 한도 (초)', 'number'], ['partitions', '내부 분할 수', 'number'],
  ['parallelism', '내부 동시 실행 한도', 'number'],
] as const
const STATUS = { pending: '대기', running: '실행 중', completed: '완료', partial: '부분 실패', failed: '실패' }

export function LiveCleaningScheduler() {
  const state = useDataStore()
  const groups = useSiloStore((s) => s.groups)
  return <div className="job-scheduler">
    <p className="desc">서버에 저장된 시각과 의존 조건에 따라 사일로의 로컬 원천을 정제합니다. 진행률은 완료한 실행 단계 기준입니다.</p>
    {state.liveError && <p role="alert" className="text-red">{state.liveError}</p>}
    <form className="silo-register-form" onSubmit={(event) => { event.preventDefault(); void state.createLiveJob() }}>
      {FIELDS.map(([key, label, type]) => <label key={key} className="control-group">{label}
        <input className="model-input" type={type} value={state.liveDraft[key]} onChange={(event) => state.patchLiveDraft({ [key]: event.target.value })} />
      </label>)}
      <label className="control-group">대상 그룹<select className="model-input" value={state.liveDraft.group_id} onChange={(event) => state.patchLiveDraft({ group_id: event.target.value })}>
        <option value="">그룹 선택</option>{groups.map((g) => <option key={g.group_id} value={g.group_id}>{g.group_id}</option>)}
      </select></label>
      <button className="btn btn-primary" disabled={state.livePending} type="submit">정제 예약 저장</button>
    </form>
    {state.liveCleaningJobs.map((job) => <div className="glass-panel content-card" key={job.jobId}>
      <p><strong>{job.jobId}</strong> · {job.occurrence}회차 / 재예약 {job.generation} · {STATUS[job.status]} · 단계 진행 {job.progress}%</p>
      <p>실행 시각: {job.scheduledAt ? new Date(job.scheduledAt).toLocaleString() : '즉시'} · 주기: {job.intervalSeconds ? `${job.intervalSeconds}초` : '1회'} · 선행: {job.dependsOn?.join(', ') || '없음'}</p>
      <p>{job.attempts}</p>{job.errors?.map((error) => <p className="text-red" key={error}>{error}</p>)}
      <button className="model-action" type="button" disabled={state.livePending} onClick={() => void state.rescheduleLiveJob(job.jobId, new Date().toISOString())}>현재 시각으로 재예약</button>
      <label>재예약 시각<input className="model-input" type="datetime-local" value={state.liveDraft[`reschedule:${job.jobId}`] ?? ''} onChange={(event) => state.patchLiveDraft({ [`reschedule:${job.jobId}`]: event.target.value })} /></label>
      <button className="model-action" type="button" disabled={state.livePending || !state.liveDraft[`reschedule:${job.jobId}`]} onClick={() => void state.rescheduleLiveJob(job.jobId, state.liveDraft[`reschedule:${job.jobId}`])}>지정 시각으로 재예약</button>
    </div>)}
  </div>
}
