import { useEffect, useState } from 'react'
import { ALGORITHM_OPTIONS } from '@/constants/simulation'
import { resolveUiDataMode, UNCONFIGURED_API_MESSAGE } from '@/lib/uiMode'
import { MODEL_PROJECTS, useModelStore } from '@/store/useModelStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { Algorithm } from '@/types/simulation'

interface NewModelFormProps {
  defaultProject: string
  onClose: () => void
}

/** 모델 등록 공통 폼 — 데모·실서버 등록 경로를 같은 레이아웃에 둔다 */
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
  const [accuracy, setAccuracy] = useState(90)
  const [rounds, setRounds] = useState(20)
  const [note, setNote] = useState('')
  const [advancedOpen, setAdvancedOpen] = useState(mode === 'live')

  useEffect(() => {
    if (mode === 'live') void refresh()
  }, [mode, refresh])

  const demoCanSubmit = version.trim().length > 0

  const submitDemo = (event: React.FormEvent) => {
    event.preventDefault()
    if (!demoCanSubmit) return
    addModel({ project, version, algorithm, accuracy, rounds, note })
    onClose()
  }

  const submitLive = (event: React.FormEvent) => {
    event.preventDefault()
    void createLive().then((ok) => {
      if (ok) onClose()
    })
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
    <form className="model-form glass-panel" onSubmit={mode === 'demo' ? submitDemo : submitLive}>
      <div className="model-form-grid">
        <div className="control-group">
          <label htmlFor="new-model-project">{mode === 'demo' ? '프로젝트' : '등록 원본'}</label>
          {mode === 'demo' ? (
            <div className="select-wrapper">
              <select id="new-model-project" value={project} onChange={(e) => setProject(e.target.value)}>
                {MODEL_PROJECTS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <select
              id="new-model-project"
              value={liveDraft.mode}
              disabled={pending}
              onChange={(event) => patchLive({ mode: event.target.value as 'training' | 'artifact' })}
            >
              <option value="training">완료된 실제 학습 결과</option>
              <option value="artifact">저장된 ridge artifact</option>
            </select>
          )}
        </div>

        <div className="control-group">
          <label htmlFor="new-model-version">버전</label>
          <input
            id="new-model-version"
            type="text"
            className="model-input"
            value={mode === 'demo' ? version : liveDraft.version}
            placeholder={mode === 'live' ? '1.0.1' : 'v0.0'}
            disabled={mode === 'live' && pending}
            onChange={(e) => (mode === 'demo' ? setVersion(e.target.value) : patchLive({ version: e.target.value }))}
          />
        </div>

        {mode === 'demo' && (
          <>
            <div className="control-group">
              <label htmlFor="new-model-algorithm">합산 알고리즘</label>
              <div className="select-wrapper">
                <select
                  id="new-model-algorithm"
                  value={algorithm}
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
                value={accuracy}
                onChange={(e) => setAccuracy(Number(e.target.value))}
              />
            </div>
            <div className="control-group">
              <label htmlFor="new-model-rounds">학습 라운드 수</label>
              <input
                id="new-model-rounds"
                type="number"
                className="model-input"
                min={1}
                value={rounds}
                onChange={(e) => setRounds(Number(e.target.value))}
              />
            </div>
            <div className="control-group model-form-note">
              <label htmlFor="new-model-note">비고 (선택)</label>
              <input
                id="new-model-note"
                type="text"
                className="model-input"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </div>
          </>
        )}
      </div>

      <button
        type="button"
        className="drift-settings-header"
        aria-expanded={advancedOpen}
        onClick={() => setAdvancedOpen((v) => !v)}
      >
        <span className="drift-settings-title">고급 · 실서버 등록 필드</span>
      </button>
      {advancedOpen && mode === 'live' && (
        <div className="model-form-grid">
          {liveDraft.mode === 'training' ? (
            <div className="control-group">
              <label htmlFor="live-model-round">완료 라운드</label>
              <select
                id="live-model-round"
                value={liveDraft.round_id}
                disabled={pending}
                onChange={(event) => patchLive({ round_id: event.target.value })}
              >
                <option value="">실제 결과를 선택하세요</option>
                {results.map((round) => (
                  <option key={round.round_id} value={round.round_id}>
                    {round.round_id} · {round.result?.result_id}
                  </option>
                ))}
              </select>
              <button type="button" className="btn btn-secondary" disabled={pending} onClick={() => void refresh()}>
                결과 새로고침
              </button>
            </div>
          ) : (
            <>
              <div className="control-group">
                <label htmlFor="live-model-name">모델 이름</label>
                <input
                  id="live-model-name"
                  className="model-input"
                  value={liveDraft.name}
                  disabled={pending}
                  onChange={(event) => patchLive({ name: event.target.value })}
                />
              </div>
              <div className="control-group">
                <label htmlFor="live-model-weights">weights.json 경로</label>
                <input
                  id="live-model-weights"
                  className="model-input"
                  value={liveDraft.weights_path}
                  disabled={pending}
                  onChange={(event) => patchLive({ weights_path: event.target.value })}
                />
              </div>
            </>
          )}
        </div>
      )}

      {error && <p role="alert">{error}</p>}

      <div className="model-form-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose} disabled={pending}>
          취소
        </button>
        <button type="submit" className="btn btn-primary" disabled={mode === 'demo' ? !demoCanSubmit : pending}>
          <i className="fa-solid fa-floppy-disk" /> {mode === 'demo' ? '모델 등록' : '실제 모델 등록'}
        </button>
      </div>
    </form>
  )
}
