import { useEffect, useState } from 'react'
import type { TrainingRoundSummary } from '@/api/client'
import { liveTrainingRequest } from '@/lib/liveTraining'
import { useLiveTrainingStore } from '@/store/useLiveTrainingStore'
import { useDataStore } from '@/store/useDataStore'
import { useSiloStore } from '@/store/useSiloStore'

export { liveTrainingRequest } from '@/lib/liveTraining'

export function LiveRoundResult({ round }: { round: TrainingRoundSummary }) {
  return round.result?.parameters?.length ? <>
    <p>영속 결과: {round.result.result_id} · checksum {round.result.checksum}</p>
    <p>파라미터 [{round.result.parameters.join(', ')}]</p>
  </> : <p>{round.status === 'completed' ? '과거 결과 파라미터 미보존' : '결과 준비 중'}</p>
}

const FIELDS = [
  ['job_id', '학습 작업 ID'], ['model_name', '등록 모델 이름'], ['version', '등록 모델 버전'],
  ['features', '특징 순서 (쉼표 구분)'], ['target', '타깃 열'], ['initial', '최초 파라미터 (특징 순서, 마지막 편향)'],
  ['l2', 'Ridge 정규화'], ['step_size', '학습률'], ['steps', '로컬 업데이트 횟수'],
  ['max_rounds', '연속 라운드 수'], ['min_contributions', '중앙 대표 정족수'],
] as const

export function LiveTrainingScheduler() {
  const groups = useSiloStore((state) => state.groups)
  const cleaning = useDataStore((state) => state.liveCleaningJobs)
  const [draft, setDraft] = useState<Record<string, string>>({ job_id: '', model_name: '', version: '1.0.0',
    group_id: '', cleaning_job_id: '', features: 'x1,x2,x3', target: 'y', initial: '0,0,0,0',
    l2: '0.001', step_size: '0.0001', steps: '1', max_rounds: '2', min_contributions: '1' })
  const jobs = useLiveTrainingStore((state) => state.jobs)
  const rounds = useLiveTrainingStore((state) => state.rounds)
  const serverError = useLiveTrainingStore((state) => state.error)
  const pending = useLiveTrainingStore((state) => state.pending)
  const observe = useLiveTrainingStore((state) => state.observe)
  const mutate = useLiveTrainingStore((state) => state.mutate)
  const [formError, setFormError] = useState<string | null>(null)
  useEffect(() => observe(), [observe])
  const error = formError ?? serverError
  return <section className="job-scheduler" aria-label="실제 연합학습">
    <h3>정제 출력으로 연속 학습</h3>
    <p>첫 초기값에서 학습하고 다음 라운드는 직전 전역 결과를 사용합니다. 집계자도 자기 데이터로 학습하며 하위 결과는 실제 전송 후 합산합니다.</p>
    {error && <p role="alert" className="text-red">{error}</p>}
    <form className="silo-register-form" onSubmit={(event) => {
      event.preventDefault()
      try { setFormError(null); void mutate('/api/training-jobs', liveTrainingRequest(draft)) }
      catch (reason) { setFormError(reason instanceof Error ? reason.message : String(reason)) }
    }}>
      {FIELDS.map(([key, label]) => <label className="control-group" key={key}>{label}
        <input className="model-input" required value={draft[key]} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} />
      </label>)}
      <label className="control-group">학습 루트 그룹<select required className="model-input" value={draft.group_id} onChange={(event) => setDraft({ ...draft, group_id: event.target.value,
        min_contributions: String(groups.find((group) => group.group_id === event.target.value)?.member_node_ids.length ?? 1) })}>
        <option value="">그룹 선택</option>{groups.filter((group) => !group.aggregator_node_id).map((group) => <option key={group.group_id} value={group.group_id}>{group.group_id}</option>)}
      </select></label>
      <label className="control-group">정제 작업<select required className="model-input" value={draft.cleaning_job_id} onChange={(event) => setDraft({ ...draft, cleaning_job_id: event.target.value })}>
        <option value="">작업 선택</option>{cleaning.map((job) => <option key={job.jobId} value={job.jobId}>{job.jobId} · {job.status}</option>)}
      </select></label>
      <button type="submit" className="btn btn-primary" disabled={pending}>학습 예약 저장</button>
    </form>
    {jobs.map((job) => <article key={job.job_id} className="glass-panel content-card">
      <p>{job.job_id} · {job.status} · 완료 {job.rounds_completed}/{job.max_rounds}</p>
      {job.error && <p className="text-red">{job.error}</p>}
      {(job.status === 'active' || job.status === 'paused') && <>
        <button disabled={pending} onClick={() => void mutate(`/api/training-jobs/${encodeURIComponent(job.job_id)}/${job.status === 'active' ? 'pause' : 'resume'}`)}>{job.status === 'active' ? '일시정지' : '재개'}</button>
        <button disabled={pending} onClick={() => void mutate(`/api/training-jobs/${encodeURIComponent(job.job_id)}/cancel`)}>작업 취소</button>
      </>}
    </article>)}
    {rounds.map((round) => <article key={round.round_id} className="glass-panel content-card">
      <p>라운드 {round.round_id} · {round.status} · 실제 표본 {round.total_samples}</p>
      {round.error && <p className="text-red">{round.error}</p>}
      <p>초기 모델: {round.base_checksum ?? '기존 학습 경로'} · 이전 라운드: {round.parent_round_id ?? '최초'}</p>
      <LiveRoundResult round={round} />
    </article>)}
  </section>
}
