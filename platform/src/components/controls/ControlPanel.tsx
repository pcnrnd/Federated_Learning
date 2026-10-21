import { useEffect, useMemo, useState } from 'react'
import { isLiveConfigured } from '@/api/client'
import { ALGORITHM_LABEL, ALGORITHM_OPTIONS, CONFIG_BOUNDS } from '@/constants/simulation'
import { getSimulationControls } from '@/hooks/useSimulationEngine'
import { liveTrainingRequest } from '@/lib/liveTraining'
import { LIVE_SIMULATION_RESET_REASON, resolveUiDataMode } from '@/lib/uiMode'
import { useDataStore } from '@/store/useDataStore'
import { useLiveTrainingStore } from '@/store/useLiveTrainingStore'
import { useSiloStore } from '@/store/useSiloStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { Algorithm } from '@/types/simulation'
import { Slider } from './Slider'

const TRAINING_FIELDS = [
  ['job_id', '학습 작업 ID'],
  ['model_name', '등록 모델 이름'],
  ['version', '등록 모델 버전'],
  ['features', '특징 순서 (쉼표 구분)'],
  ['target', '타깃 열'],
  ['initial', '최초 파라미터 (특징 순서, 마지막 편향)'],
  ['l2', 'Ridge 정규화'],
  ['step_size', '학습률'],
  ['steps', '로컬 업데이트 횟수'],
  ['min_contributions', '중앙 대표 정족수'],
] as const

const initialTrainingDraft = (): Record<string, string> => ({
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
  const liveJobs = useLiveTrainingStore((s) => s.jobs)
  const livePending = useLiveTrainingStore((s) => s.pending)
  const liveError = useLiveTrainingStore((s) => s.error)
  const mutate = useLiveTrainingStore((s) => s.mutate)
  const observe = useLiveTrainingStore((s) => s.observe)

  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [trainingDraft, setTrainingDraft] = useState(initialTrainingDraft)
  const [formError, setFormError] = useState<string | null>(null)

  useEffect(() => {
    if (mode !== 'live') return
    return observe()
  }, [mode, observe])

  const start = () => getSimulationControls().start()
  const pauseSim = () => getSimulationControls().pause()
  const reset = () => getSimulationControls().reset()

  const inputsDisabled = mode === 'demo' && isRunning && !isPaused
  const isFinished = mode === 'demo' && !isRunning && currentRound > 0 && currentRound >= config.totalRounds

  const activeJob = useMemo(
    () => liveJobs.find((job) => job.status === 'active' || job.status === 'paused'),
    [liveJobs],
  )

  const handleAlgorithm = (algorithm: Algorithm) => {
    setAlgorithm(algorithm)
    log('system', `합산 알고리즘 구성 변동 -> ${ALGORITHM_LABEL[algorithm]}`)
  }

  const patchDraft = (patch: Record<string, string>) => {
    setTrainingDraft((prev) => ({ ...prev, ...patch }))
  }

  const submitLiveTraining = async () => {
    setFormError(null)
    try {
      const body = liveTrainingRequest({ ...trainingDraft, max_rounds: String(config.totalRounds) })
      await mutate('/api/training-jobs', body)
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : String(reason))
    }
  }

  const onPrimaryLive = async () => {
    if (!isLiveConfigured()) return
    if (activeJob?.status === 'active') {
      await mutate(`/api/training-jobs/${encodeURIComponent(activeJob.job_id)}/pause`)
      return
    }
    if (activeJob?.status === 'paused') {
      await mutate(`/api/training-jobs/${encodeURIComponent(activeJob.job_id)}/resume`)
      return
    }
    await submitLiveTraining()
  }

  const primaryDisabled =
    mode === 'unconfigured' ||
    livePending ||
    (mode === 'live' && !activeJob && (!trainingDraft.group_id || !trainingDraft.cleaning_job_id || !trainingDraft.job_id.trim()))

  const primaryLabel =
    mode === 'demo'
      ? isPaused
        ? '학습 재개'
        : isRunning
          ? '실시간 학습 중...'
          : isFinished
            ? '학습 재시작'
            : '학습 시작'
      : activeJob?.status === 'active'
        ? '학습 일시정지'
        : activeJob?.status === 'paused'
          ? '학습 재개'
          : '실제 학습 시작'

  const roundDisplay =
    mode === 'live' && activeJob
      ? `${activeJob.rounds_completed}/${activeJob.max_rounds}`
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
            실데이터 API 주소 설정이 필요합니다. 데모를 켜거나 VITE_API_BASE를 설정하세요.
          </p>
        )}
        {mode === 'live' && (
          <p className="desc" role="status">
            실제 연합 학습 작업 {liveJobs.length}건 · 진행 라운드 {roundDisplay}. 선행 조건(그룹·정제 작업·모델)을
            고급 설정에서 지정해야 학습을 시작할 수 있습니다.
          </p>
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
                onChange={(e) => handleAlgorithm(e.target.value as Algorithm)}
              >
                {ALGORITHM_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <Slider
            id="config-rounds"
            label="총 연합 라운드 수 (Global Rounds)"
            value={config.totalRounds}
            min={CONFIG_BOUNDS.rounds.min}
            max={CONFIG_BOUNDS.rounds.max}
            display={String(config.totalRounds)}
            disabled={mode === 'live' ? livePending || Boolean(activeJob) : inputsDisabled}
            onChange={setTotalRounds}
          />

          <Slider
            id="config-epochs"
            label="로컬 학습 반복 횟수 (Local Epochs)"
            value={config.localEpochs}
            min={CONFIG_BOUNDS.epochs.min}
            max={CONFIG_BOUNDS.epochs.max}
            display={String(config.localEpochs)}
            disabled={mode !== 'demo' || inputsDisabled}
            onChange={setLocalEpochs}
          />

          <Slider
            id="config-lr"
            label="로컬 학습률 (Learning Rate)"
            value={config.learningRate}
            min={CONFIG_BOUNDS.learningRate.min}
            max={CONFIG_BOUNDS.learningRate.max}
            step={CONFIG_BOUNDS.learningRate.step}
            display={config.learningRate.toFixed(3)}
            disabled={mode !== 'demo' || inputsDisabled}
            onChange={setLearningRate}
          />
        </div>

        <div className="action-btn-row">
          <button
            type="button"
            className="btn btn-primary"
            disabled={
              mode === 'demo'
                ? (isRunning && !isPaused) || mode !== 'demo'
                : primaryDisabled
            }
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
            disabled={mode === 'demo' ? !isRunning || isPaused : !activeJob || activeJob.status !== 'active'}
            onClick={() => {
              if (mode === 'demo') pauseSim()
              else if (activeJob) void mutate(`/api/training-jobs/${encodeURIComponent(activeJob.job_id)}/pause`)
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
        </div>

        <button
          type="button"
          className="drift-settings-header"
          aria-expanded={advancedOpen}
          onClick={() => setAdvancedOpen((v) => !v)}
        >
          <span className="drift-settings-title">
            <i className="fa-solid fa-gears" /> 실제 학습 선행 조건 (그룹 · 정제 · 모델)
          </span>
          <i className={`fa-solid fa-chevron-down drift-settings-chevron${advancedOpen ? ' open' : ''}`} />
        </button>
        {advancedOpen && (
          <div className="drift-settings-body">
            {mode === 'demo' && (
              <p className="desc">데모 모드에서는 아래 필드가 비활성입니다. 실제 학습은 데모 데이터를 끈 뒤 사용하세요.</p>
            )}
            {TRAINING_FIELDS.map(([key, label]) => (
              <label key={key} className="control-group">
                {label}
                <input
                  className="model-input"
                  value={trainingDraft[key]}
                  disabled={mode !== 'live' || livePending || Boolean(activeJob)}
                  onChange={(event) => patchDraft({ [key]: event.target.value })}
                />
              </label>
            ))}
            <label className="control-group">
              학습 루트 그룹
              <select
                className="model-input"
                value={trainingDraft.group_id}
                disabled={mode !== 'live' || livePending || Boolean(activeJob)}
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
                className="model-input"
                value={trainingDraft.cleaning_job_id}
                disabled={mode !== 'live' || livePending || Boolean(activeJob)}
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
            {mode === 'live' && activeJob && (
              <button
                type="button"
                className="btn btn-secondary"
                disabled={livePending}
                onClick={() => void mutate(`/api/training-jobs/${encodeURIComponent(activeJob.job_id)}/cancel`)}
              >
                진행 중인 학습 작업 취소
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
