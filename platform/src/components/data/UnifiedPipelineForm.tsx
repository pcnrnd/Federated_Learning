import { useState, type FormEvent } from 'react'
import { liveTrainingRequest } from '@/lib/liveTraining'
import { resolveUiDataMode, UNCONFIGURED_API_MESSAGE } from '@/lib/uiMode'
import { useDataStore } from '@/store/useDataStore'
import { useLiveTrainingStore } from '@/store/useLiveTrainingStore'
import { useSiloStore } from '@/store/useSiloStore'
import { useSimulationStore } from '@/store/useSimulationStore'

const CLEANING_FIELDS = [
  ['job_id', '작업 ID', 'text'],
  ['recipe_name', '등록 레시피 이름', 'text'],
  ['recipe_version', '레시피 버전', 'text'],
  ['dataset_label', '로컬 데이터셋', 'text'],
  ['scheduled_at', '최초 실행 시각 (빈 값: 즉시)', 'datetime-local'],
  ['interval_seconds', '반복 주기 (초, 빈 값: 1회)', 'number'],
  ['depends_on', '선행 정제 ID (쉼표)', 'text'],
] as const

const TRAINING_FIELDS = [
  ['job_id', '학습 작업 ID'],
  ['model_name', '모델 이름'],
  ['version', '모델 버전'],
  ['features', '특징 (쉼표)'],
  ['target', '타깃'],
  ['initial', '초기 파라미터'],
  ['max_rounds', '연속 라운드'],
] as const

interface UnifiedPipelineFormProps {
  onClose: () => void
}

/** 데이터 탭 공통 파이프라인 등록 폼 — 데모·실서버 기능을 같은 레이아웃에 배치한다 */
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
  const cleaning = useDataStore((s) => s.liveCleaningJobs)
  const mutate = useLiveTrainingStore((s) => s.mutate)
  const trainingPending = useLiveTrainingStore((s) => s.pending)

  const [name, setName] = useState('')
  const [schedule, setSchedule] = useState('0 * * * *')
  const [dependsOn, setDependsOn] = useState<string[]>([])
  const [trainingDraft, setTrainingDraft] = useState<Record<string, string>>({
    job_id: '',
    model_name: '',
    version: '1.0.0',
    group_id: '',
    cleaning_job_id: '',
    features: 'x1,x2,x3',
    target: 'y',
    initial: '0,0,0,0',
    l2: '0.001',
    step_size: '0.0001',
    steps: '1',
    max_rounds: '2',
    min_contributions: '1',
  })
  const [formError, setFormError] = useState<string | null>(null)
  const [advancedOpen, setAdvancedOpen] = useState(mode === 'live')

  const demoCanSubmit = mode === 'demo' && name.trim().length > 0 && schedule.trim().length > 0

  const submitDemo = (event: FormEvent) => {
    event.preventDefault()
    if (!demoCanSubmit) return
    addJob({ name, schedule, dependsOn })
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
      const body = liveTrainingRequest(trainingDraft)
      const ok = await mutate('/api/training-jobs', body)
      if (ok) onClose()
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : String(reason))
    }
  }

  if (mode === 'unconfigured') {
    return (
      <form className="model-form glass-panel">
        <p className="deploy-empty" role="status">
          {UNCONFIGURED_API_MESSAGE}
        </p>
        <div className="model-form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            닫기
          </button>
        </div>
      </form>
    )
  }

  return (
    <form
      className="model-form glass-panel"
      onSubmit={mode === 'demo' ? submitDemo : submitCleaning}
    >
      <div className="model-form-grid">
        <div className="control-group">
          <label htmlFor="pipe-name">{mode === 'demo' ? '작업명' : '정제 작업 ID'}</label>
          <input
            id="pipe-name"
            className="model-input"
            value={mode === 'demo' ? name : liveDraft.job_id}
            disabled={mode === 'live' && livePending}
            onChange={(e) =>
              mode === 'demo' ? setName(e.target.value) : patchLiveDraft({ job_id: e.target.value })
            }
          />
        </div>
        <div className="control-group">
          <label htmlFor="pipe-schedule">{mode === 'demo' ? '스케줄 (cron)' : '데이터셋 라벨'}</label>
          <input
            id="pipe-schedule"
            className="model-input"
            value={mode === 'demo' ? schedule : liveDraft.dataset_label}
            disabled={mode === 'live' && livePending}
            onChange={(e) =>
              mode === 'demo'
                ? setSchedule(e.target.value)
                : patchLiveDraft({ dataset_label: e.target.value })
            }
          />
        </div>
        {mode === 'demo' && (
          <div className="control-group model-form-note">
            <label>선행 의존 ({dependsOn.length})</label>
            <div className="edge-node-grid">
              {jobs.map((j) => (
                <button
                  key={j.id}
                  type="button"
                  className={`edge-node-chip${dependsOn.includes(j.id) ? ' active' : ''}`}
                  onClick={() =>
                    setDependsOn((prev) =>
                      prev.includes(j.id) ? prev.filter((id) => id !== j.id) : [...prev, j.id],
                    )
                  }
                >
                  {j.name}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <button
        type="button"
        className="drift-settings-header"
        aria-expanded={advancedOpen}
        onClick={() => setAdvancedOpen((v) => !v)}
      >
        <span className="drift-settings-title">고급 · 실서버 정제·학습 필드</span>
      </button>
      {advancedOpen && mode === 'live' && (
        <div className="model-form-grid">
          {CLEANING_FIELDS.map(([key, label, type]) => (
            <label key={key} className="control-group">
              {label}
              <input
                className="model-input"
                type={type}
                value={liveDraft[key]}
                disabled={livePending}
                onChange={(event) => patchLiveDraft({ [key]: event.target.value })}
              />
            </label>
          ))}
          <label className="control-group">
            대상 그룹
            <select
              className="model-input"
              value={liveDraft.group_id}
              disabled={livePending}
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
          {TRAINING_FIELDS.map(([key, label]) => (
            <label key={key} className="control-group">
              {label}
              <input
                className="model-input"
                value={trainingDraft[key]}
                disabled={trainingPending}
                onChange={(event) => setTrainingDraft({ ...trainingDraft, [key]: event.target.value })}
              />
            </label>
          ))}
          <label className="control-group">
            정제 작업 (학습 입력)
            <select
              className="model-input"
              value={trainingDraft.cleaning_job_id}
              disabled={trainingPending}
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
          <label className="control-group">
            학습 그룹
            <select
              className="model-input"
              value={trainingDraft.group_id}
              disabled={trainingPending}
              onChange={(event) => setTrainingDraft({ ...trainingDraft, group_id: event.target.value })}
            >
              <option value="">그룹 선택</option>
              {groups.filter((g) => !g.aggregator_node_id).map((g) => (
                <option key={g.group_id} value={g.group_id}>
                  {g.group_id}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      {formError && <p role="alert">{formError}</p>}

      <div className="model-form-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          취소
        </button>
        {mode === 'demo' ? (
          <button type="submit" className="btn btn-primary" disabled={!demoCanSubmit}>
            파이프라인 등록
          </button>
        ) : (
          <>
            <button type="submit" className="btn btn-primary" disabled={livePending}>
              정제 예약 저장
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={trainingPending}
              onClick={() => void submitTraining({ preventDefault: () => {} } as React.FormEvent)}
            >
              연합 학습 예약 저장
            </button>
          </>
        )}
      </div>
      {mode === 'demo' && silos.length === 0 && (
        <p className="desc">데모 사일로가 없으면 작업만 등록됩니다.</p>
      )}
    </form>
  )
}
