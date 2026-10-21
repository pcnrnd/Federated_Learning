import { useEffect, useState } from 'react'
import { ALGORITHM_OPTIONS } from '@/constants/simulation'
import { MAIN_MODEL_FIELD_IDS } from '@/lib/pipelineFields'
import {
  LIVE_DEMO_CAPABILITY_REASON,
  LIVE_METRIC_FIELD_REASON,
  resolveUiDataMode,
  UNCONFIGURED_API_MESSAGE,
} from '@/lib/uiMode'
import { MODEL_PROJECTS, useModelStore } from '@/store/useModelStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { Algorithm } from '@/types/simulation'

interface NewModelFormProps {
  defaultProject: string
  onClose: () => void
}

export { MAIN_MODEL_FIELD_IDS }

export function NewModelForm({ defaultProject, onClose }: NewModelFormProps) {
  const mockEnabled = useSimulationStore((state) => state.mockEnabled)
  const mode = resolveUiDataMode(mockEnabled)
  const addModel = useModelStore((s) => s.addModel)
  const liveDraft = useModelStore((s) => s.liveModelDraft)
  const patchLive = useModelStore((s) => s.patchLiveModelDraft)
  const results = useModelStore((s) => s.liveModelResults)
  const refresh = useModelStore((s) => s.loadLiveModelResults)
  const createLive = useModelStore((s) => s.createLiveModel)
  const pending = useModelStore((s) => s.liveModelPending)
  const error = useModelStore((s) => s.liveModelError)

  const [project, setProject] = useState(defaultProject)
  const [version, setVersion] = useState('')
  const [algorithm, setAlgorithm] = useState<Algorithm>('fedavg')
  const [accuracy, setAccuracy] = useState<number | ''>(90)
  const [rounds, setRounds] = useState<number | ''>(20)
  const [note, setNote] = useState('')

  const mainDisabled = mode !== 'demo'
  const liveDisabled = mode !== 'live' || pending
  const demoCanSubmit = mode === 'demo' && version.trim().length > 0

  useEffect(() => {
    if (mode === 'live') void refresh()
  }, [mode, refresh])

  useEffect(() => {
    if (mode === 'live' || mode === 'unconfigured') {
      setAccuracy('')
      setRounds('')
    } else {
      setAccuracy(90)
      setRounds(20)
    }
  }, [mode])

  const submitDemo = (event: React.FormEvent) => {
    event.preventDefault()
    if (!demoCanSubmit || accuracy === '' || rounds === '') return
    addModel({ project, version, algorithm, accuracy, rounds, note })
    onClose()
  }

  const submitLive = (event: React.FormEvent) => {
    event.preventDefault()
    void createLive().then((ok) => {
      if (ok) onClose()
    })
  }

  return (
    <form
      className="model-form glass-panel"
      onSubmit={
        mode === 'demo'
          ? submitDemo
          : mode === 'live'
            ? submitLive
            : (event) => event.preventDefault()
      }
    >
      {mode === 'unconfigured' && (
        <p className="deploy-empty" role="status">
          {UNCONFIGURED_API_MESSAGE}
        </p>
      )}
      <div className="model-form-grid">
        <div className="control-group">
          <label htmlFor="new-model-project">프로젝트</label>
          <div className="select-wrapper">
            <select
              id="new-model-project"
              value={project}
              disabled={mainDisabled}
              title={mainDisabled ? LIVE_DEMO_CAPABILITY_REASON : undefined}
              onChange={(e) => setProject(e.target.value)}
            >
              {MODEL_PROJECTS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="control-group">
          <label htmlFor="new-model-version">버전 (예: v2.4)</label>
          <input
            id="new-model-version"
            type="text"
            className="model-input"
            value={mode === 'live' ? liveDraft.version : version}
            placeholder="v0.0"
            disabled={mode === 'live' ? liveDisabled : mainDisabled && mode === 'unconfigured'}
            onChange={(e) =>
              mode === 'live' ? patchLive({ version: e.target.value }) : setVersion(e.target.value)
            }
          />
        </div>

        <div className="control-group">
          <label htmlFor="new-model-algorithm">합산 알고리즘</label>
          <div className="select-wrapper">
            <select
              id="new-model-algorithm"
              value={algorithm}
              disabled={mainDisabled}
              title={mainDisabled ? LIVE_METRIC_FIELD_REASON : undefined}
              onChange={(e) => setAlgorithm(e.target.value as Algorithm)}
            >
              {ALGORITHM_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="control-group">
          <label htmlFor="new-model-accuracy">정확도 (%)</label>
          <input
            id="new-model-accuracy"
            type="number"
            className="model-input"
            min={0}
            max={100}
            step={0.1}
            value={mode === 'demo' ? accuracy : ''}
            disabled={mainDisabled}
            placeholder={mainDisabled ? '—' : undefined}
            title={mainDisabled ? LIVE_METRIC_FIELD_REASON : undefined}
            onChange={(e) => setAccuracy(e.target.value === '' ? '' : Number(e.target.value))}
          />
        </div>

        <div className="control-group">
          <label htmlFor="new-model-rounds">학습 라운드 수</label>
          <input
            id="new-model-rounds"
            type="number"
            className="model-input"
            min={1}
            value={mode === 'demo' ? rounds : ''}
            disabled={mainDisabled}
            placeholder={mainDisabled ? '—' : undefined}
            title={mainDisabled ? LIVE_METRIC_FIELD_REASON : undefined}
            onChange={(e) => setRounds(e.target.value === '' ? '' : Number(e.target.value))}
          />
        </div>

        <div className="control-group model-form-note">
          <label htmlFor="new-model-note">비고 (선택)</label>
          <input
            id="new-model-note"
            type="text"
            className="model-input"
            value={note}
            disabled={mainDisabled}
            placeholder={mainDisabled ? '—' : '배포 메모 / 변경 사항'}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
      </div>

      <details className="parity-advanced-section">
        <summary>실서버 등록 원본 · 결과/artifact</summary>
        <div className="model-form-grid">
          <div className="control-group">
            <label htmlFor="live-model-source">등록 원본</label>
            <select
              id="live-model-source"
              value={liveDraft.mode}
              disabled={liveDisabled || mode !== 'live'}
              title={mode !== 'live' ? LIVE_DEMO_CAPABILITY_REASON : undefined}
              onChange={(event) => patchLive({ mode: event.target.value as 'training' | 'artifact' })}
            >
              <option value="training">완료된 실제 학습 결과</option>
              <option value="artifact">저장된 ridge artifact</option>
            </select>
          </div>
          <div className="control-group">
            <label htmlFor="live-model-round">완료 라운드</label>
            <select
              id="live-model-round"
              value={liveDraft.round_id}
              disabled={liveDisabled || mode !== 'live'}
              onChange={(event) => patchLive({ round_id: event.target.value })}
            >
              <option value="">실제 결과를 선택하세요</option>
              {results.map((round) => (
                <option key={round.round_id} value={round.round_id}>
                  {round.round_id} · {round.result?.result_id}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={liveDisabled || mode !== 'live'}
              onClick={() => void refresh()}
            >
              결과 새로고침
            </button>
          </div>
          <div className="control-group">
            <label htmlFor="live-model-name">모델 이름 (artifact)</label>
            <input
              id="live-model-name"
              className="model-input"
              value={liveDraft.name}
              disabled={liveDisabled || mode !== 'live'}
              onChange={(event) => patchLive({ name: event.target.value })}
            />
          </div>
          <div className="control-group">
            <label htmlFor="live-model-weights">weights.json 경로</label>
            <input
              id="live-model-weights"
              className="model-input"
              value={liveDraft.weights_path}
              disabled={liveDisabled || mode !== 'live'}
              onChange={(event) => patchLive({ weights_path: event.target.value })}
            />
          </div>
        </div>
      </details>

      {error && <p role="alert">{error}</p>}

      <div className="model-form-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose} disabled={pending}>
          취소
        </button>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={mode === 'demo' ? !demoCanSubmit : mode !== 'live' || pending}
        >
          <i className="fa-solid fa-floppy-disk" /> {mode === 'demo' ? '모델 등록' : '실제 모델 등록'}
        </button>
      </div>
    </form>
  )
}
