import { useEffect, useMemo, useState } from 'react'
import {
  demoJobsToSchedulerRows,
  liveCleaningToSchedulerRows,
  liveTrainingToSchedulerRows,
  type SchedulerRow,
} from '@/lib/liveJobDisplay'
import { resolveUiDataMode, UNCONFIGURED_API_MESSAGE } from '@/lib/uiMode'
import { useDataStore } from '@/store/useDataStore'
import { useLiveTrainingStore } from '@/store/useLiveTrainingStore'
import { useSiloStore } from '@/store/useSiloStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { JobState } from '@/types/simulation'
import { UnifiedPipelineForm } from './UnifiedPipelineForm'

const STATE_LABEL: Record<JobState, string> = {
  queued: '대기',
  running: '실행중',
  done: '완료',
  failed: '실패',
}

const STATE_CLASS: Record<JobState, string> = {
  queued: 'dep-state-pending',
  running: 'dep-state-deploying',
  done: 'dep-state-done',
  failed: 'dep-state-failed',
}

function dependsLabel(job: SchedulerRow, jobs: SchedulerRow[]): string {
  if (job.dependsOn.length === 0) return '없음'
  return job.dependsOn.map((id) => jobs.find((j) => j.id === id)?.name ?? id).join(', ')
}

export function JobScheduler() {
  const mockEnabled = useSimulationStore((s) => s.mockEnabled)
  const mode = resolveUiDataMode(mockEnabled)
  const jobs = useDataStore((s) => s.jobs)
  const canRun = useDataStore((s) => s.canRun)
  const runJob = useDataStore((s) => s.runJob)
  const pauseJob = useDataStore((s) => s.pauseJob)
  const removeJob = useDataStore((s) => s.removeJob)
  const liveCleaningJobs = useDataStore((s) => s.liveCleaningJobs)
  const livePending = useDataStore((s) => s.livePending)
  const rescheduleLiveJob = useDataStore((s) => s.rescheduleLiveJob)
  const liveDraft = useDataStore((s) => s.liveDraft)
  const patchLiveDraft = useDataStore((s) => s.patchLiveDraft)
  const silos = useSiloStore((s) => s.silos)

  const trainingJobs = useLiveTrainingStore((s) => s.jobs)
  const trainingPending = useLiveTrainingStore((s) => s.pending)
  const mutate = useLiveTrainingStore((s) => s.mutate)
  const observe = useLiveTrainingStore((s) => s.observe)

  const [showForm, setShowForm] = useState(false)

  useEffect(() => {
    if (mode !== 'live') return
    return observe()
  }, [mode, observe])

  const rows = useMemo(() => {
    if (mode === 'demo') return demoJobsToSchedulerRows(jobs)
    return [...liveCleaningToSchedulerRows(liveCleaningJobs), ...liveTrainingToSchedulerRows(trainingJobs)]
  }, [mode, jobs, liveCleaningJobs, trainingJobs])

  const siloName = (id?: number): string => {
    if (id === undefined) return '전체'
    return silos.find((s) => s.id === id)?.name ?? `사일로 #${id}`
  }

  const runnable = mode === 'demo' ? jobs.filter((j) => canRun(j.id)) : []
  const runAllEligible = () => runnable.forEach((j) => runJob(j.id))

  const emptyMessage =
    mode === 'unconfigured'
      ? UNCONFIGURED_API_MESSAGE
      : mode === 'live'
        ? '등록된 실서버 작업이 없습니다. 파이프라인 등록으로 정제·학습을 예약하세요.'
        : '등록된 파이프라인 작업이 없습니다. “파이프라인 등록”으로 추가하세요.'

  return (
    <div className="job-scheduler">
      <div className="job-toolbar">
        <span className="desc">
          {mode === 'demo'
            ? '의존성이 충족된 작업은 병렬로 동시에 실행됩니다.'
            : '실서버 정제·연합학습 작업 상태입니다. 재예약·일시정지·취소는 행별 액션을 사용하세요.'}
        </span>
        <div className="job-toolbar-actions">
          {mode === 'demo' && (
            <button
              type="button"
              className="model-action deploy"
              disabled={runnable.length === 0}
              onClick={runAllEligible}
            >
              <i className="fa-solid fa-play" /> 대기 작업 모두 실행 ({runnable.length})
            </button>
          )}
          <button type="button" className="btn-new-model" onClick={() => setShowForm((v) => !v)}>
            <i className={`fa-solid ${showForm ? 'fa-xmark' : 'fa-plus'}`} />{' '}
            {showForm ? '닫기' : '파이프라인 등록'}
          </button>
        </div>
      </div>

      {showForm && <UnifiedPipelineForm onClose={() => setShowForm(false)} />}

      <div className="model-table-wrapper">
        <table className="model-table">
          <thead>
            <tr>
              <th>작업명</th>
              <th>대상 사일로</th>
              <th>스케줄 (cron)</th>
              <th>의존 작업</th>
              <th>상태</th>
              <th className="ta-right">액션</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((job) => {
              const running = job.state === 'running'
              const eligible = mode === 'demo' && canRun(job.id)
              const blocked = job.state === 'queued' && mode === 'demo' && !eligible
              const training = trainingJobs.find((t) => t.job_id === job.id)
              return (
                <tr key={`${job.kind}:${job.id}`}>
                  <td className="model-version-cell">{job.name}</td>
                  <td className="model-algo-cell">{siloName(job.targetSiloId)}</td>
                  <td className="model-date-cell">{job.schedule}</td>
                  <td className="model-algo-cell">{dependsLabel(job, rows)}</td>
                  <td>
                    <span className={`dep-state-badge ${STATE_CLASS[job.state]}`}>
                      {running && <i className="fa-solid fa-spinner fa-spin" />}
                      {blocked ? '대기 (선행 필요)' : STATE_LABEL[job.state]}
                    </span>
                  </td>
                  <td>
                    <div className="model-row-actions">
                      {job.kind === 'demo' &&
                        (running ? (
                          <button type="button" className="model-action" onClick={() => pauseJob(job.id)}>
                            <i className="fa-solid fa-pause" /> 일시중지
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="model-action deploy"
                            disabled={!eligible}
                            onClick={() => runJob(job.id)}
                          >
                            <i className="fa-solid fa-play" /> 작업 실행
                          </button>
                        ))}
                      {job.kind === 'cleaning' && mode === 'live' && (
                        <>
                          <button
                            type="button"
                            className="model-action deploy"
                            disabled={livePending}
                            onClick={() => void rescheduleLiveJob(job.id, new Date().toISOString())}
                          >
                            재예약(즉시)
                          </button>
                          <input
                            className="model-input"
                            type="datetime-local"
                            value={liveDraft[`reschedule:${job.id}`] ?? ''}
                            onChange={(event) => patchLiveDraft({ [`reschedule:${job.id}`]: event.target.value })}
                          />
                          <button
                            type="button"
                            className="model-action"
                            disabled={livePending || !liveDraft[`reschedule:${job.id}`]}
                            onClick={() =>
                              void rescheduleLiveJob(job.id, liveDraft[`reschedule:${job.id}`] as string)
                            }
                          >
                            지정 시각 재예약
                          </button>
                        </>
                      )}
                      {job.kind === 'training' && training && (
                        <>
                          {(training.status === 'active' || training.status === 'paused') && (
                            <button
                              type="button"
                              className="model-action"
                              disabled={trainingPending}
                              onClick={() =>
                                void mutate(
                                  `/api/training-jobs/${encodeURIComponent(training.job_id)}/${
                                    training.status === 'active' ? 'pause' : 'resume'
                                  }`,
                                )
                              }
                            >
                              {training.status === 'active' ? '일시정지' : '재개'}
                            </button>
                          )}
                          {(training.status === 'active' || training.status === 'paused') && (
                            <button
                              type="button"
                              className="model-action remove"
                              disabled={trainingPending}
                              onClick={() =>
                                void mutate(`/api/training-jobs/${encodeURIComponent(training.job_id)}/cancel`)
                              }
                            >
                              취소
                            </button>
                          )}
                        </>
                      )}
                      {job.kind === 'demo' && (
                        <button type="button" className="model-action remove" onClick={() => removeJob(job.id)}>
                          <i className="fa-solid fa-trash" /> 삭제
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="model-empty">
                  {emptyMessage}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
