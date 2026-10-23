import type { ReactNode } from 'react'
import { Pager, usePaged } from '@/components/common/Pager'
import { formatNumber } from '@/lib/format'
import { useDataStore } from '@/store/useDataStore'
import { useLiveTrainingStore } from '@/store/useLiveTrainingStore'
import type { CleaningJobStatus } from '@/types/simulation'
import { CounterList } from './CleansingGrid'
import { LiveRoundResult } from './LiveTrainingScheduler'

const CLEANING_STATUS: Record<CleaningJobStatus, string> = {
  pending: '대기',
  running: '진행중',
  completed: '완료',
  partial: '부분 실패',
  failed: '실패',
}

/** 접힌 결과 블록 — 드리프트 설정 패널과 같은 제목·셰브런 톤 */
function ResultBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="drift-settings-panel parity-advanced-section pipeline-result">
      <summary className="drift-settings-header">
        <span className="drift-settings-title">{title}</span>
        <i className="fa-solid fa-chevron-down drift-settings-chevron" aria-hidden="true" />
      </summary>
      <div className="drift-settings-body">{children}</div>
    </details>
  )
}

/** JobScheduler 하단 — 실서버 정제·학습 결과/계보 표시. 블록은 10개씩 페이지로 나눈다. */
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

  const blocks: ReactNode[] = [
    ...cleaningJobs.map((job) => (
      <ResultBlock key={`c:${job.jobId}`} title={`정제 ${job.jobId} · ${CLEANING_STATUS[job.status]} · ${job.progress ?? 0}%`}>
        <p className="desc">
          {job.recipe} · {job.datasetLabel} · 입력 {formatNumber(job.totalRowsIn)} → 출력 {formatNumber(job.totalRowsOut)}
        </p>
        <CounterList counters={job.counters} />
        {job.errors?.map((error) => (
          <p className="text-red" key={error}>
            {error}
          </p>
        ))}
        {job.attempts && <p className="desc">{job.attempts}</p>}
        <div className="silo-group-actions">
          <button
            type="button"
            className="model-action"
            disabled={livePending}
            onClick={() => void rescheduleLiveJob(job.jobId, new Date().toISOString())}
          >
            현재 시각으로 재예약
          </button>
          <input
            aria-label="재예약 시각"
            className="model-input"
            type="datetime-local"
            value={liveDraft[`reschedule:${job.jobId}`] ?? ''}
            onChange={(event) => patchLiveDraft({ [`reschedule:${job.jobId}`]: event.target.value })}
          />
          <button
            type="button"
            className="model-action"
            disabled={livePending || !liveDraft[`reschedule:${job.jobId}`]}
            onClick={() => void rescheduleLiveJob(job.jobId, liveDraft[`reschedule:${job.jobId}`] as string)}
          >
            지정 시각으로 재예약
          </button>
        </div>
      </ResultBlock>
    )),
    ...trainingJobs.map((job) => (
      <ResultBlock key={`t:${job.job_id}`} title={`학습 ${job.job_id} · ${job.status} · ${job.rounds_completed}/${job.max_rounds}`}>
        {job.error && <p className="text-red">{job.error}</p>}
        {job.status === 'active' || job.status === 'paused' ? (
          <div className="silo-group-actions">
            <button
              type="button"
              className="model-action"
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
              className="model-action remove"
              disabled={pending}
              onClick={() => void mutate(`/api/training-jobs/${encodeURIComponent(job.job_id)}/cancel`)}
            >
              작업 취소
            </button>
          </div>
        ) : (
          <p className="desc">종료된 작업입니다.</p>
        )}
      </ResultBlock>
    )),
    ...rounds.map((round) => (
      <ResultBlock key={`r:${round.round_id}`} title={`라운드 ${round.round_id} · ${round.status} · 표본 ${round.total_samples}`}>
        {round.error && <p className="text-red">{round.error}</p>}
        <p className="desc">
          초기 모델: {round.base_checksum ?? '기존 학습 경로'} · 이전 라운드: {round.parent_round_id ?? '최초'}
        </p>
        <LiveRoundResult round={round} />
      </ResultBlock>
    )),
  ]
  const paged = usePaged(blocks)

  if (blocks.length === 0) return null

  return (
    <div className="pipeline-live-results">
      <div className="data-subhead">
        <i className="fa-solid fa-layer-group" /> 정제·학습 결과
      </div>
      {paged.items}
      <Pager paged={paged} label="정제·학습 결과 페이지" />
    </div>
  )
}
