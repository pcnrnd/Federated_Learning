import { formatNumber } from '@/lib/format'
import { useDataStore } from '@/store/useDataStore'
import { useLiveTrainingStore } from '@/store/useLiveTrainingStore'
import type { CleaningJobStatus } from '@/types/simulation'
import { LiveRoundResult } from './LiveTrainingScheduler'

const CLEANING_STATUS: Record<CleaningJobStatus, string> = {
  pending: '대기',
  running: '진행중',
  completed: '완료',
  partial: '부분 실패',
  failed: '실패',
}

/** JobScheduler 하단 — 실서버 정제·학습 결과/계보 표시 */
export function PipelineLiveResults() {
  const cleaningJobs = useDataStore((s) => s.liveCleaningJobs)
  const liveDraft = useDataStore((s) => s.liveDraft)
  const patchLiveDraft = useDataStore((s) => s.patchLiveDraft)
  const livePending = useDataStore((s) => s.livePending)
  const rescheduleLiveJob = useDataStore((s) => s.rescheduleLiveJob)
  const trainingJobs = useLiveTrainingStore((s) => s.jobs)
  const rounds = useLiveTrainingStore((s) => s.rounds)
  const pending = useLiveTrainingStore((s) => s.pending)
  const mutate = useLiveTrainingStore((s) => s.mutate)

  if (cleaningJobs.length === 0 && trainingJobs.length === 0 && rounds.length === 0) return null

  return (
    <div className="pipeline-live-results">
      {cleaningJobs.map((job) => (
        <details key={job.jobId} className="glass-panel content-card" open={false}>
          <summary>
            정제 {job.jobId} · {CLEANING_STATUS[job.status]} · {job.progress ?? 0}%
          </summary>
          <p>
            {job.recipe} · {job.datasetLabel} · 입력 {formatNumber(job.totalRowsIn)} → 출력{' '}
            {formatNumber(job.totalRowsOut)}
          </p>
          <p>
            step 카운터:{' '}
            {Object.entries(job.counters)
              .map(([step, n]) => `${step} ${formatNumber(n)}`)
              .join(' · ') || '—'}
          </p>
          {job.errors?.map((error) => (
            <p className="text-red" key={error}>
              {error}
            </p>
          ))}
          {job.attempts && <p>{job.attempts}</p>}
          <button
            type="button"
            className="model-action"
            disabled={livePending}
            onClick={() => void rescheduleLiveJob(job.jobId, new Date().toISOString())}
          >
            현재 시각으로 재예약
          </button>
          <label>
            재예약 시각
            <input
              className="model-input"
              type="datetime-local"
              value={liveDraft[`reschedule:${job.jobId}`] ?? ''}
              onChange={(event) => patchLiveDraft({ [`reschedule:${job.jobId}`]: event.target.value })}
            />
          </label>
          <button
            type="button"
            className="model-action"
            disabled={livePending || !liveDraft[`reschedule:${job.jobId}`]}
            onClick={() => void rescheduleLiveJob(job.jobId, liveDraft[`reschedule:${job.jobId}`] as string)}
          >
            지정 시각으로 재예약
          </button>
        </details>
      ))}

      {trainingJobs.map((job) => (
        <details key={job.job_id} className="glass-panel content-card" open={false}>
          <summary>
            학습 {job.job_id} · {job.status} · {job.rounds_completed}/{job.max_rounds}
          </summary>
          {job.error && <p className="text-red">{job.error}</p>}
          {(job.status === 'active' || job.status === 'paused') && (
            <div className="model-row-actions">
              <button
                type="button"
                disabled={pending}
                onClick={() =>
                  void mutate(
                    `/api/training-jobs/${encodeURIComponent(job.job_id)}/${job.status === 'active' ? 'pause' : 'resume'}`,
                  )
                }
              >
                {job.status === 'active' ? '일시정지' : '재개'}
              </button>
              <button
                type="button"
                disabled={pending}
                onClick={() => void mutate(`/api/training-jobs/${encodeURIComponent(job.job_id)}/cancel`)}
              >
                작업 취소
              </button>
            </div>
          )}
        </details>
      ))}

      {rounds.map((round) => (
        <details key={round.round_id} className="glass-panel content-card" open={false}>
          <summary>
            라운드 {round.round_id} · {round.status} · 표본 {round.total_samples}
          </summary>
          {round.error && <p className="text-red">{round.error}</p>}
          <p>
            초기 모델: {round.base_checksum ?? '기존 학습 경로'} · 이전 라운드:{' '}
            {round.parent_round_id ?? '최초'}
          </p>
          <LiveRoundResult round={round} />
        </details>
      ))}
    </div>
  )
}
