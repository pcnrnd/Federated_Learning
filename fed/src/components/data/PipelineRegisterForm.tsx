import { useState } from 'react'
import { useDataStore } from '@/store/useDataStore'
import { useSiloStore } from '@/store/useSiloStore'

interface PipelineRegisterFormProps {
  onClose: () => void
}

const ALL_SILOS = 'all' as const

export function PipelineRegisterForm({ onClose }: PipelineRegisterFormProps) {
  const addJob = useDataStore((s) => s.addJob)
  const jobs = useDataStore((s) => s.jobs)
  const silos = useSiloStore((s) => s.silos)

  const [name, setName] = useState('')
  const [schedule, setSchedule] = useState('0 * * * *')
  const [target, setTarget] = useState<string>(ALL_SILOS)
  const [dependsOn, setDependsOn] = useState<string[]>([])

  const canSubmit = name.trim().length > 0 && schedule.trim().length > 0

  const toggleDep = (id: string) => {
    setDependsOn((prev) => (prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    addJob({
      name,
      schedule,
      dependsOn,
      ...(target !== ALL_SILOS ? { targetSiloId: Number(target) } : {}),
    })
    onClose()
  }

  return (
    <form className="model-form glass-panel" onSubmit={handleSubmit}>
      <div className="model-form-grid">
        <div className="control-group">
          <label htmlFor="new-job-name">작업명</label>
          <input
            id="new-job-name"
            type="text"
            className="model-input"
            value={name}
            placeholder="예: 이상치 제거 (Outlier)"
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div className="control-group">
          <label htmlFor="new-job-schedule">스케줄 (cron / 주기)</label>
          <input
            id="new-job-schedule"
            type="text"
            className="model-input"
            value={schedule}
            placeholder="0 * * * *"
            onChange={(e) => setSchedule(e.target.value)}
          />
        </div>

        <div className="control-group">
          <label htmlFor="new-job-target">대상 사일로</label>
          <div className="select-wrapper">
            <select id="new-job-target" value={target} onChange={(e) => setTarget(e.target.value)}>
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
                  onClick={() => toggleDep(j.id)}
                >
                  {j.name}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="model-form-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          취소
        </button>
        <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
          <i className="fa-solid fa-plus" /> 파이프라인 등록
        </button>
      </div>
    </form>
  )
}
