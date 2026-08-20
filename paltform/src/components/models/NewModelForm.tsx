import { useState } from 'react'
import { ALGORITHM_OPTIONS } from '@/constants/simulation'
import { MODEL_PROJECTS, useModelStore } from '@/store/useModelStore'
import type { Algorithm } from '@/types/simulation'

interface NewModelFormProps {
  defaultProject: string
  onClose: () => void
}

export function NewModelForm({ defaultProject, onClose }: NewModelFormProps) {
  const addModel = useModelStore((s) => s.addModel)

  const [project, setProject] = useState(defaultProject)
  const [version, setVersion] = useState('')
  const [algorithm, setAlgorithm] = useState<Algorithm>('fedavg')
  const [accuracy, setAccuracy] = useState(90)
  const [rounds, setRounds] = useState(20)
  const [note, setNote] = useState('')

  const canSubmit = version.trim().length > 0

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    addModel({ project, version, algorithm, accuracy, rounds, note })
    onClose()
  }

  return (
    <form className="model-form glass-panel" onSubmit={handleSubmit}>
      <div className="model-form-grid">
        <div className="control-group">
          <label htmlFor="new-model-project">프로젝트</label>
          <div className="select-wrapper">
            <select
              id="new-model-project"
              value={project}
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
            value={version}
            placeholder="v0.0"
            onChange={(e) => setVersion(e.target.value)}
          />
        </div>

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
            placeholder="배포 메모 / 변경 사항"
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
      </div>

      <div className="model-form-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          취소
        </button>
        <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
          <i className="fa-solid fa-floppy-disk" /> 모델 등록
        </button>
      </div>
    </form>
  )
}
