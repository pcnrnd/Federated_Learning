import { useState } from 'react'
import { useDataStore } from '@/store/useDataStore'
import { useSiloStore } from '@/store/useSiloStore'
import type { Job, JobState } from '@/types/simulation'
import { PipelineRegisterForm } from './PipelineRegisterForm'

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

function dependsLabel(job: Job, jobs: Job[]): string {
  if (job.dependsOn.length === 0) return '없음'
  return job.dependsOn.map((id) => jobs.find((j) => j.id === id)?.name ?? id).join(', ')
}

export function JobScheduler() {
  const jobs = useDataStore((s) => s.jobs)
  const canRun = useDataStore((s) => s.canRun)
  const runJob = useDataStore((s) => s.runJob)
  const pauseJob = useDataStore((s) => s.pauseJob)
  const removeJob = useDataStore((s) => s.removeJob)
  const silos = useSiloStore((s) => s.silos)

  const [showForm, setShowForm] = useState(false)

  const siloName = (id?: number): string => {
    if (id === undefined) return '전체'
    return silos.find((s) => s.id === id)?.name ?? `사일로 #${id}`
  }

  const runnable = jobs.filter((j) => canRun(j.id))
  const runAllEligible = () => runnable.forEach((j) => runJob(j.id))

  return (
    <div className="job-scheduler">
      <div className="job-toolbar">
        <span className="desc">의존성이 충족된 작업은 병렬로 동시에 실행됩니다.</span>
        <div className="job-toolbar-actions">
          <button
            type="button"
            className="model-action deploy"
            disabled={runnable.length === 0}
            onClick={runAllEligible}
          >
            <i className="fa-solid fa-play" /> 대기 작업 모두 실행 ({runnable.length})
          </button>
          <button type="button" className="btn-new-model" onClick={() => setShowForm((v) => !v)}>
            <i className={`fa-solid ${showForm ? 'fa-xmark' : 'fa-plus'}`} />{' '}
            {showForm ? '닫기' : '파이프라인 등록'}
          </button>
        </div>
      </div>

      {showForm && <PipelineRegisterForm onClose={() => setShowForm(false)} />}

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
            {jobs.map((job) => {
              const running = job.state === 'running'
              const eligible = canRun(job.id)
              const blocked = job.state === 'queued' && !eligible
              return (
                <tr key={job.id}>
                  <td className="model-version-cell">{job.name}</td>
                  <td className="model-algo-cell">{siloName(job.targetSiloId)}</td>
                  <td className="model-date-cell">{job.schedule}</td>
                  <td className="model-algo-cell">{dependsLabel(job, jobs)}</td>
                  <td>
                    <span className={`dep-state-badge ${STATE_CLASS[job.state]}`}>
                      {running && <i className="fa-solid fa-spinner fa-spin" />}
                      {blocked ? '대기 (선행 필요)' : STATE_LABEL[job.state]}
                    </span>
                  </td>
                  <td>
                    <div className="model-row-actions">
                      {running ? (
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
                      )}
                      <button type="button" className="model-action remove" onClick={() => removeJob(job.id)}>
                        <i className="fa-solid fa-trash" /> 삭제
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
            {jobs.length === 0 && (
              <tr>
                <td colSpan={6} className="model-empty">
                  등록된 파이프라인 작업이 없습니다. “파이프라인 등록”으로 추가하세요.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
