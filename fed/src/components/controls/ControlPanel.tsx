import { ALGORITHM_LABEL, ALGORITHM_OPTIONS, CONFIG_BOUNDS } from '@/constants/simulation'
import { useSimulationEngine } from '@/hooks/useSimulationEngine'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { Algorithm } from '@/types/simulation'
import { Slider } from './Slider'

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
  const { start, pause, reset } = useSimulationEngine()

  const inputsDisabled = isRunning && !isPaused
  const isFinished = !isRunning && currentRound > 0 && currentRound >= config.totalRounds

  const handleAlgorithm = (algorithm: Algorithm) => {
    setAlgorithm(algorithm)
    log('system', `합산 알고리즘 구성 변동 -> ${ALGORITHM_LABEL[algorithm]}`)
  }

  const startLabel = isPaused
    ? '학습 재개'
    : isRunning
      ? '실시간 학습 중...'
      : isFinished
        ? '학습 재시작'
        : '학습 시작'

  return (
    <div className="glass-panel content-card">
      <div className="card-header">
        <h3>
          <i className="fa-solid fa-sliders" /> 시뮬레이션 구성 및 제어
        </h3>
        <span className="desc">Simulation Settings</span>
      </div>
      <div className="card-body">
        <div className="control-grid-vertical">
          <div className="control-group">
            <label htmlFor="config-algorithm">합산 알고리즘 (Aggregation Method)</label>
            <div className="select-wrapper">
              <select
                id="config-algorithm"
                value={config.algorithm}
                disabled={inputsDisabled}
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
            disabled={inputsDisabled}
            onChange={setTotalRounds}
          />

          <Slider
            id="config-epochs"
            label="로컬 학습 반복 횟수 (Local Epochs)"
            value={config.localEpochs}
            min={CONFIG_BOUNDS.epochs.min}
            max={CONFIG_BOUNDS.epochs.max}
            display={String(config.localEpochs)}
            disabled={inputsDisabled}
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
            disabled={inputsDisabled}
            onChange={setLearningRate}
          />
        </div>

        <div className="action-btn-row">
          <button
            type="button"
            className="btn btn-primary"
            disabled={isRunning && !isPaused}
            onClick={start}
          >
            <i className={`fa-solid ${isRunning && !isPaused ? 'fa-spinner fa-spin' : 'fa-play'}`} />{' '}
            {startLabel}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={!isRunning || isPaused}
            onClick={pause}
          >
            <i className="fa-solid fa-pause" /> 일시 정지
          </button>
          <button type="button" className="btn btn-danger" onClick={reset}>
            <i className="fa-solid fa-rotate-left" /> 초기화
          </button>
        </div>
      </div>
    </div>
  )
}
