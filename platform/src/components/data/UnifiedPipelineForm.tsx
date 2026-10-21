import { useState, type FormEvent } from 'react'
import { liveTrainingRequest } from '@/lib/liveTraining'
import {
  CLEANING_FORM_FIELDS,
  initialTrainingDraftRecord,
  MAIN_PIPELINE_FIELD_IDS,
  TRAINING_FORM_FIELDS,
} from '@/lib/pipelineFields'
import {
  LIVE_CRON_FIELD_REASON,
  LIVE_DEMO_CAPABILITY_REASON,
  resolveUiDataMode,
  UNCONFIGURED_API_MESSAGE,
} from '@/lib/uiMode'
import { useDataStore } from '@/store/useDataStore'
import { useLiveTrainingStore } from '@/store/useLiveTrainingStore'
import { useSiloStore } from '@/store/useSiloStore'
import { useSimulationStore } from '@/store/useSimulationStore'

export { MAIN_PIPELINE_FIELD_IDS }

const ALL_SILOS = 'all' as const

interface UnifiedPipelineFormProps {
  onClose: () => void
}

export function UnifiedPipelineForm({ onClose }: UnifiedPipelineFormProps) {
  const mockEnabled = useSimulationStore((s) => s.mockEnabled)
  const mode = resolveUiDataMode(mockEnabled)
  const addJob = useDataStore((s) => s.addJob)
  const jobs = useDataStore((s) => s.jobs)
  const silos = useSiloStore((s) => s.silos)
  const groups = useSiloStore((s) => s.groups)
  const liveDraft = useDataStore((s) => s.liveDraft)
  const patchLiveDraft = useDataStore((s) => s.patchLiveDraft)
  const createLiveJob = useDataStore((s) => s.createLiveJob)
  const livePending = useDataStore((s) => s.livePending)
  const liveError = useDataStore((s) => s.liveError)
  const cleaning = useDataStore((s) => s.liveCleaningJobs)
  const mutate = useLiveTrainingStore((s) => s.mutate)
  const trainingPending = useLiveTrainingStore((s) => s.pending)
  const trainingError = useLiveTrainingStore((s) => s.error)

  const [name, setName] = useState('')
  const [schedule, setSchedule] = useState('0 * * * *')
  const [target, setTarget] = useState<string>(ALL_SILOS)
  const [dependsOn, setDependsOn] = useState<string[]>([])
  const [trainingDraft, setTrainingDraft] = useState(initialTrainingDraftRecord)
  const [formError, setFormError] = useState<string | null>(null)

  const demoEditable = mode === 'demo'
  const liveEditable = mode === 'live' && !livePending && !trainingPending

  const demoCanSubmit = demoEditable && name.trim().length > 0 && schedule.trim().length > 0

  const toggleDep = (id: string) => {
    if (!demoEditable) return
    setDependsOn((prev) => (prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]))
  }

  const submitDemo = (event: FormEvent) => {
    event.preventDefault()
    if (!demoCanSubmit) return
    addJob({
      name,
      schedule,
      dependsOn,
      ...(target !== ALL_SILOS ? { targetSiloId: Number(target) } : {}),
    })
    onClose()
  }

  const submitCleaning = async (event: FormEvent) => {
    event.preventDefault()
    setFormError(null)
    const ok = await createLiveJob()
    if (ok) onClose()
  }

  const submitTraining = async (event: FormEvent) => {
    event.preventDefault()
    setFormError(null)
    try {
      const ok = await mutate('/api/training-jobs', liveTrainingRequest(trainingDraft))
      if (ok) onClose()
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : String(reason))
    }
  }

  const displayError = formError ?? liveError ?? trainingError

  return (
    <form className="model-form glass-panel" onSubmit={demoEditable ? submitDemo : (event) => event.preventDefault()}>
      {mode === 'unconfigured' && (
        <p className="deploy-empty" role="status">
          {UNCONFIGURED_API_MESSAGE}
        </p>
      )}

      <div className="model-form-grid">
        <div className="control-group">
          <label htmlFor="new-job-name">작업명</label>
          <input
            id="new-job-name"
            type="text"
            className="model-input"
            value={demoEditable ? name : liveDraft.job_id}
            disabled={mode === 'unconfigured'}
            placeholder={demoEditable ? '예: 이상치 제거 (Outlier)' : '작업 ID'}
            onChange={(e) =>
              demoEditable ? setName(e.target.value) : patchLiveDraft({ job_id: e.target.value })
            }
          />
        </div>

        <div className="control-group">
          <label htmlFor="new-job-schedule">스케줄 (cron / 주기)</label>
          <input
            id="new-job-schedule"
            type="text"
            className="model-input"
            value={demoEditable ? schedule : ''}
            disabled={!demoEditable}
            placeholder={demoEditable ? '0 * * * *' : '—'}
            title={!demoEditable ? LIVE_CRON_FIELD_REASON : undefined}
            onChange={(e) => setSchedule(e.target.value)}
          />
          {!demoEditable && <p className="desc">{LIVE_CRON_FIELD_REASON}</p>}
        </div>

        <div className="control-group">
          <label htmlFor="new-job-target">대상 사일로</label>
          <div className="select-wrapper">
            <select
              id="new-job-target"
              value={target}
              disabled={!demoEditable}
              title={!demoEditable ? LIVE_DEMO_CAPABILITY_REASON : undefined}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value={ALL_SILOS}>전체 사일로</option>
              {silos.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="control-group model-form-note">
          <label>선행 의존 작업 ({dependsOn.length}개 선택)</label>
          {jobs.length === 0 ? (
            <span className="desc">등록된 작업이 없습니다. 의존성 없이 등록됩니다.</span>
          ) : (
            <div className="edge-node-grid">
              {jobs.map((j) => (
                <button
                  key={j.id}
                  type="button"
                  className={`edge-node-chip${dependsOn.includes(j.id) ? ' active' : ''}`}
                  disabled={!demoEditable}
                  onClick={() => toggleDep(j.id)}
                >
                  {j.name}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <details id="pipe-cleaning-advanced" className="parity-advanced-section">
        <summary>고급 · 실서버 정제 예약 (LiveCleaningScheduler)</summary>
        <div className="model-form-grid">
          {CLEANING_FORM_FIELDS.map(([key, label, type]) => (
            <label key={key} className="control-group">
              {label}
              <input
                id={`pipe-cleaning-${key}`}
                className="model-input"
                type={type}
                value={liveDraft[key]}
                disabled={!liveEditable}
                onChange={(event) => patchLiveDraft({ [key]: event.target.value })}
              />
            </label>
          ))}
          <label className="control-group">
            대상 그룹
            <select
              className="model-input"
              value={liveDraft.group_id}
              disabled={!liveEditable}
              onChange={(event) => patchLiveDraft({ group_id: event.target.value })}
            >
              <option value="">그룹 선택</option>
              {groups.map((g) => (
                <option key={g.group_id} value={g.group_id}>
                  {g.group_id}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!liveEditable}
            onClick={() => void submitCleaning({ preventDefault: () => {} } as FormEvent)}
          >
            정제 예약 저장
          </button>
        </div>
      </details>

      <details id="pipe-training-advanced" className="parity-advanced-section">
        <summary>고급 · 실서버 연합 학습 (LiveTrainingScheduler)</summary>
        <div className="model-form-grid">
          {TRAINING_FORM_FIELDS.map(([key, label]) => (
            <label key={key} className="control-group">
              {label}
              <input
                id={`pipe-training-${key}`}
                className="model-input"
                value={trainingDraft[key]}
                disabled={!liveEditable}
                onChange={(event) => setTrainingDraft({ ...trainingDraft, [key]: event.target.value })}
              />
            </label>
          ))}
          <label className="control-group">
            학습 루트 그룹
            <select
              className="model-input"
              value={trainingDraft.group_id}
              disabled={!liveEditable}
              onChange={(event) =>
                setTrainingDraft({
                  ...trainingDraft,
                  group_id: event.target.value,
                  min_contributions: String(
                    groups.find((group) => group.group_id === event.target.value)?.member_node_ids.length ?? 1,
                  ),
                })
              }
            >
              <option value="">그룹 선택</option>
              {groups.filter((group) => !group.aggregator_node_id).map((group) => (
                <option key={group.group_id} value={group.group_id}>
                  {group.group_id}
                </option>
              ))}
            </select>
          </label>
          <label className="control-group">
            정제 작업
            <select
              className="model-input"
              value={trainingDraft.cleaning_job_id}
              disabled={!liveEditable}
              onChange={(event) => setTrainingDraft({ ...trainingDraft, cleaning_job_id: event.target.value })}
            >
              <option value="">작업 선택</option>
              {cleaning.map((job) => (
                <option key={job.jobId} value={job.jobId}>
                  {job.jobId} · {job.status}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn btn-primary" disabled={!liveEditable} onClick={() => void submitTraining({ preventDefault: () => {} } as FormEvent)}>
            학습 예약 저장
          </button>
        </div>
      </details>

      {displayError && <p role="alert" className="text-red">{displayError}</p>}

      <div className="model-form-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          {demoEditable ? '취소' : '닫기'}
        </button>
        {demoEditable && (
          <button type="submit" className="btn btn-primary" disabled={!demoCanSubmit}>
            <i className="fa-solid fa-plus" /> 파이프라인 등록
          </button>
        )}
      </div>
    </form>
  )
}
