import { useState } from 'react'
import { useSiloStore } from '@/store/useSiloStore'

interface SiloRegisterFormProps {
  onClose: () => void
}

export function SiloRegisterForm({ onClose }: SiloRegisterFormProps) {
  const addSilo = useSiloStore((s) => s.addSilo)

  const [name, setName] = useState('')
  const [endpoint, setEndpoint] = useState('')
  const [collectIntervalSec, setCollectIntervalSec] = useState(15)

  const canSubmit = name.trim().length > 0 && endpoint.trim().length > 0

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    addSilo({ name, endpoint, collectIntervalSec })
    onClose()
  }

  return (
    <form className="model-form glass-panel" onSubmit={handleSubmit}>
      <div className="model-form-grid">
        <div className="control-group">
          <label htmlFor="new-silo-name">사일로명</label>
          <input
            id="new-silo-name"
            type="text"
            className="model-input"
            value={name}
            placeholder="예: 사일로13"
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div className="control-group">
          <label htmlFor="new-silo-endpoint">엔드포인트 (base_url)</label>
          <input
            id="new-silo-endpoint"
            type="text"
            className="model-input"
            value={endpoint}
            placeholder="tcp://10.0.x.x:2375"
            onChange={(e) => setEndpoint(e.target.value)}
          />
        </div>

        <div className="control-group">
          <label htmlFor="new-silo-interval">파라미터 수집 주기 (초)</label>
          <input
            id="new-silo-interval"
            type="number"
            className="model-input"
            min={5}
            value={collectIntervalSec}
            onChange={(e) => setCollectIntervalSec(Number(e.target.value))}
          />
        </div>
      </div>

      <div className="model-form-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          취소
        </button>
        <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
          <i className="fa-solid fa-plus" /> 사일로 등록
        </button>
      </div>
    </form>
  )
}
