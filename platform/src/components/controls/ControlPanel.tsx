import { useEffect, useState } from 'react'
import { isLiveConfigured } from '@/api/client'
import { ALGORITHM_LABEL, ALGORITHM_OPTIONS, CONFIG_BOUNDS } from '@/constants/simulation'
import { getSimulationControls } from '@/hooks/useSimulationEngine'
import { liveTrainingRequest } from '@/lib/liveTraining'
import { trainingJobActionPath } from '@/lib/trainingJobPaths'
import {
  CLEANING_FORM_FIELDS,
  initialTrainingDraftRecord,
  TRAINING_FORM_FIELDS,
} from '@/lib/pipelineFields'
import {
  LIVE_ALGORITHM_REASON,
  LIVE_JOB_SELECT_REASON,
  LIVE_SIMULATION_RESET_REASON,
  resolveUiDataMode,
  UNCONFIGURED_API_MESSAGE,
} from '@/lib/uiMode'
import { useDataStore } from '@/store/useDataStore'
import { useLiveTrainingStore } from '@/store/useLiveTrainingStore'
import { useSiloStore } from '@/store/useSiloStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { Algorithm } from '@/types/simulation'
import { Slider } from './Slider'

const ADVANCED_PREREQ_KEYS = [
  'job_id',
  'model_name',
  'version',
  'features',
  'target',
  'initial',
  'l2',
  'min_contributions',
] as const

export function ControlPanel() {
  const config = useSimulationStore((s) => s.config)
  const isRunning = useSimulationStore((s) => s.isRunning)
  const isPaused = useSimulationStore((s) => s.isPaused)
  const currentRound = useSimulationStore((s) => s.currentRound)
  const setAlgorithm = useSimulationStore((s) => s.setAlgorithm)
  const setTotalRounds = useSimulationStore((s) => s.setTotalRounds)
  const setLocalEpochs = useSimulationStore((s) => s.setLocalEpochs)
  const setLearningRate = useSimulationStore((s) => s.setLearningRate)
  const log = useSimulationStore((s) => s.log)
  const mockEnabled = useSimulationStore((s) => s.mockEnabled)
  const mode = resolveUiDataMode(mockEnabled)

  const groups = useSiloStore((s) => s.groups)
  const cleaning = useDataStore((s) => s.liveCleaningJobs)
  const liveDraft = useDataStore((s) => s.liveDraft)
  const patchLiveDraft = useDataStore((s) => s.patchLiveDraft)
  const liveJobs = useLiveTrainingStore((s) => s.jobs)
  const livePending = useLiveTrainingStore((s) => s.pending)
  const liveError = useLiveTrainingStore((s) => s.error)
  const mutate = useLiveTrainingStore((s) => s.mutate)
  const observe = useLiveTrainingStore((s) => s.observe)

  const [selectedJobId, setSelectedJobId] = useState('')
  const [trainingDraft, setTrainingDraft] = useState(initialTrainingDraftRecord)
  const [formError, setFormError] = useState<string | null>(null)

  useEffect(() => {
    if (mode !== 'live') return
    return observe()
  }, [mode, observe])

  const selectedJob = liveJobs.find((job) => job.job_id === selectedJobId) ?? null

  const start = () => getSimulationControls().start()
  const pauseSim = () => getSimulationControls().pause()
  const reset = () => getSimulationControls().reset()

  const inputsDisabled = mode === 'demo' && isRunning && !isPaused
  const isFinished = mode === 'demo' && !isRunning && currentRound > 0 && currentRound >= config.totalRounds
  const liveControlsDisabled = mode !== 'live' || livePending

  const patchDraft = (patch: Record<string, string>) => {
    setTrainingDraft((prev) => ({ ...prev, ...patch }))
  }

  const syncLiveSteps = (epochs: number) => {
    setLocalEpochs(epochs)
    patchDraft({ steps: String(epochs) })
  }

  const syncLiveLearningRate = (lr: number) => {
    setLearningRate(lr)
    patchDraft({ step_size: String(lr) })
  }

  const syncLiveMaxRounds = (rounds: number) => {
    setTotalRounds(rounds)
    patchDraft({ max_rounds: String(rounds) })
  }

  useEffect(() => {
    if (mode !== 'live') return
    patchDraft({
      steps: String(config.localEpochs),
      step_size: String(config.learningRate),
      max_rounds: String(config.totalRounds),
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode])

  const handleAlgorithm = (algorithm: Algorithm) => {
    setAlgorithm(algorithm)
    log('system', `합산 알고리즘 구성 변동 -> ${ALGORITHM_LABEL[algorithm]}`)
  }

  const prerequisitesReady = () =>
    Boolean(
      trainingDraft.group_id &&
        trainingDraft.cleaning_job_id &&
        trainingDraft.job_id.trim() &&
        ADVANCED_PREREQ_KEYS.every((key) => trainingDraft[key]?.trim()),
    )

  const submitLiveTraining = async () => {
    setFormError(null)
    try {
      const body = liveTrainingRequest({
        ...trainingDraft,
        steps: String(config.localEpochs),
        step_size: String(config.learningRate),
        max_rounds: String(config.totalRounds),
      })
      const ok = await mutate('/api/training-jobs', body)
      if (ok) setSelectedJobId(trainingDraft.job_id.trim())
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : String(reason))
    }
  }

  const onPrimaryLive = async () => {
    if (!isLiveConfigured()) return
    setFormError(null)
    if (selectedJob?.status === 'active') {
      await mutate(trainingJobActionPath(selectedJob.job_id, 'pause'))
      return
    }
    if (selectedJob?.status === 'paused') {
      await mutate(trainingJobActionPath(selectedJob.job_id, 'resume'))
      return
    }
    if (!prerequisitesReady()) {
      setFormError('고급 설정에서 그룹·정제 작업·모델·특징을 모두 지정하세요.')
      return
    }
    await submitLiveTraining()
  }

  const primaryDisabledLive =
    livePending || (selectedJob ? false : !prerequisitesReady())

  const primaryLabel =
    mode === 'demo'
      ? isPaused
        ? '학습 재개'
        : isRunning
          ? '실시간 학습 중...'
          : isFinished
            ? '학습 재시작'
            : '학습 시작'
      : selectedJob?.status === 'active'
        ? '선택 작업 일시정지'
        : selectedJob?.status === 'paused'
          ? '선택 작업 재개'
          : '실제 학습 시작'

  const roundDisplay = selectedJob
    ? `${selectedJob.rounds_completed}/${selectedJob.max_rounds}`
    : String(currentRound)

  return (
    <div className="glass-panel content-card">
      <div className="card-header">
        <h3>
          <i className="fa-solid fa-sliders" /> 시뮬레이션 구성 및 제어
        </h3>
        <span className="desc">Simulation Settings</span>
      </div>
      <div className="card-body">
        {mode === 'unconfigured' && (
          <p className="deploy-empty" role="status">
            {UNCONFIGURED_API_MESSAGE}
          </p>
        )}
        {mode === 'live' && (
          <>
            <label className="control-group" htmlFor="control-live-training-job">
              실제 학습 작업 선택
            </label>
            <select
              id="control-live-training-job"
              className="model-input"
              value={selectedJobId}
              disabled={liveControlsDisabled}
              onChange={(event) => {
                setFormError(null)
                setSelectedJobId(event.target.value)
              }}
            >
              <option value="">작업 선택 (일시정지·재개·취소에 필요)</option>
              {liveJobs.map((job) => (
                <option key={job.job_id} value={job.job_id}>
                  {job.job_id} · {job.status} · {job.rounds_completed}/{job.max_rounds}
                </option>
              ))}
            </select>
            <p className="desc" role="status">
              등록된 학습 작업 {liveJobs.length}건 · 선택 작업 라운드 {roundDisplay}
            </p>
          </>
        )}
        {(liveError || formError) && (
          <p className="text-red" role="alert">
            {formError ?? liveError}
          </p>
        )}

        <div className="control-grid-vertical">
          <div className="control-group">
            <label htmlFor="config-algorithm">합산 알고리즘 (Aggregation Method)</label>
            <div className="select-wrapper">
              <select
                id="config-algorithm"
                value={config.algorithm}
                disabled={mode !== 'demo' || inputsDisabled}
                title={mode !== 'demo' ? LIVE_ALGORITHM_REASON : undefined}
                onChange={(e) => handleAlgorithm(e.target.value as Algorithm)}
              >
                {ALGORITHM_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            {mode !== 'demo' && <p className="desc">{LIVE_ALGORITHM_REASON}</p>}
          </div>

          <Slider
            id="config-rounds"
            label="총 연합 라운드 수 (Global Rounds)"
            value={config.totalRounds}
            min={CONFIG_BOUNDS.rounds.min}
            max={CONFIG_BOUNDS.rounds.max}
            display={String(config.totalRounds)}
            disabled={liveControlsDisabled || (mode === 'demo' && inputsDisabled)}
            onChange={(value) => (mode === 'live' ? syncLiveMaxRounds(value) : setTotalRounds(value))}
          />

          <Slider
            id="config-epochs"
            label="로컬 학습 반복 횟수 (Local Epochs)"
            value={config.localEpochs}
            min={CONFIG_BOUNDS.epochs.min}
            max={CONFIG_BOUNDS.epochs.max}
            display={String(config.localEpochs)}
            disabled={liveControlsDisabled || (mode === 'demo' && inputsDisabled)}
            onChange={(value) => (mode === 'live' ? syncLiveSteps(value) : setLocalEpochs(value))}
          />

          <Slider
            id="config-lr"
            label="로컬 학습률 (Learning Rate)"
            value={config.learningRate}
            min={CONFIG_BOUNDS.learningRate.min}
            max={CONFIG_BOUNDS.learningRate.max}
            step={CONFIG_BOUNDS.learningRate.step}
            display={config.learningRate.toFixed(3)}
            disabled={liveControlsDisabled || (mode === 'demo' && inputsDisabled)}
            onChange={(value) => (mode === 'live' ? syncLiveLearningRate(value) : setLearningRate(value))}
          />
        </div>

        <div className="action-btn-row">
          <button
            type="button"
            className="btn btn-primary"
            disabled={mode === 'demo' ? (isRunning && !isPaused) || mode !== 'demo' : primaryDisabledLive}
            onClick={() => {
              if (mode === 'demo') start()
              else void onPrimaryLive()
            }}
          >
            <i
              className={`fa-solid ${
                (mode === 'demo' && isRunning && !isPaused) || livePending ? 'fa-spinner fa-spin' : 'fa-play'
              }`}
            />{' '}
            {primaryLabel}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={
              mode === 'demo'
                ? !isRunning || isPaused
                : liveControlsDisabled || !selectedJob || selectedJob.status !== 'active'
            }
            title={mode === 'live' && !selectedJob ? LIVE_JOB_SELECT_REASON : undefined}
            onClick={() => {
              if (mode === 'demo') pauseSim()
              else if (selectedJob) void mutate(trainingJobActionPath(selectedJob.job_id, 'pause'))
            }}
          >
            <i className="fa-solid fa-pause" /> 일시 정지
          </button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={mode !== 'demo'}
            title={mode !== 'demo' ? LIVE_SIMULATION_RESET_REASON : undefined}
            onClick={reset}
          >
            <i className="fa-solid fa-rotate-left" /> 초기화
          </button>
          {mode === 'live' && (
            <button
              type="button"
              className="btn btn-secondary"
              disabled={liveControlsDisabled || !selectedJob}
              title={!selectedJob ? LIVE_JOB_SELECT_REASON : undefined}
              onClick={() => {
                if (!selectedJob) return
                void mutate(trainingJobActionPath(selectedJob.job_id, 'cancel'))
              }}
            >
              선택 작업 취소
            </button>
          )}
        </div>

        <details className="parity-advanced-section">
          <summary>실제 학습 선행 조건 · 정제/학습 고급 필드</summary>
          <div className="drift-settings-body">
            {mode !== 'live' && (
              <p className="desc">실서버 연동 시에만 편집할 수 있습니다. 필드 레이아웃은 모든 모드에서 동일합니다.</p>
            )}
            {TRAINING_FORM_FIELDS.map(([key, label]) => {
              const sliderBound = key === 'steps' || key === 'step_size' || key === 'max_rounds'
              const value =
                key === 'steps'
                  ? String(config.localEpochs)
                  : key === 'step_size'
                    ? String(config.learningRate)
                    : key === 'max_rounds'
                      ? String(config.totalRounds)
                      : trainingDraft[key]
              return (
                <label key={key} className="control-group">
                  {label}
                  <input
                    id={`control-training-${key}`}
                    className="model-input"
                    value={value}
                    disabled={mode !== 'live' || livePending || sliderBound}
                    title={sliderBound ? '메인 슬라이더와 연동됩니다.' : undefined}
                    onChange={(event) => patchDraft({ [key]: event.target.value })}
                  />
                </label>
              )
            })}
            <label className="control-group">
              학습 루트 그룹
              <select
                id="control-training-group"
                className="model-input"
                value={trainingDraft.group_id}
                disabled={mode !== 'live' || livePending}
                onChange={(event) =>
                  patchDraft({
                    group_id: event.target.value,
                    min_contributions: String(
                      groups.find((group) => group.group_id === event.target.value)?.member_node_ids.length ?? 1,
                    ),
                  })
                }
              >
                <option value="">그룹 선택</option>
                {groups
                  .filter((group) => !group.aggregator_node_id)
                  .map((group) => (
                    <option key={group.group_id} value={group.group_id}>
                      {group.group_id}
                    </option>
                  ))}
              </select>
            </label>
            <label className="control-group">
              정제 작업
              <select
                id="control-training-cleaning"
                className="model-input"
                value={trainingDraft.cleaning_job_id}
                disabled={mode !== 'live' || livePending}
                onChange={(event) => patchDraft({ cleaning_job_id: event.target.value })}
              >
                <option value="">작업 선택</option>
                {cleaning.map((job) => (
                  <option key={job.jobId} value={job.jobId}>
                    {job.jobId} · {job.status}
                  </option>
                ))}
              </select>
            </label>
            <p className="data-subhead">정제 예약 필드 (LiveCleaningScheduler 동일)</p>
            {CLEANING_FORM_FIELDS.map(([key, label, type]) => (
              <label key={key} className="control-group">
                {label}
                <input
                  id={`control-cleaning-${key}`}
                  className="model-input"
                  type={type}
                  value={liveDraft[key] ?? ''}
                  disabled={mode !== 'live' || livePending}
                  onChange={(event) => patchLiveDraft({ [key]: event.target.value })}
                />
              </label>
            ))}
          </div>
        </details>
      </div>
    </div>
  )
}
