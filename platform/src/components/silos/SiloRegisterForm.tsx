import { useState } from 'react'
import { useSiloStore } from '@/store/useSiloStore'

interface SiloRegisterFormProps {
  onClose: () => void
}

export function SiloRegisterForm({ onClose }: SiloRegisterFormProps) {
  const addSilo = useSiloStore((s) => s.addSilo)
  const silos = useSiloStore((s) => s.silos)

  // 계층 깊이는 2단 — 상위로 지정할 수 있는 건 1단 사일로뿐이다
  const parentOptions = silos.filter((s) => s.parentId === undefined)

  const [name, setName] = useState('')
  const [endpoint, setEndpoint] = useState('')
  const [collectIntervalSec, setCollectIntervalSec] = useState(15)
  const [parentId, setParentId] = useState<number | ''>('')

  const canSubmit = name.trim().length > 0 && endpoint.trim().length > 0 && parentId !== ''

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    // canSubmit이 parentId !== '' 를 포함하므로 여기서 parentId는 number로 좁혀진다
    if (!canSubmit) return
    addSilo({ name, endpoint, collectIntervalSec, parentId })
    onClose()
  }

  return (
    <form className="model-form glass-panel" onSubmit={handleSubmit}>
      <div className="model-form-grid">
        <div className="control-group">
          <label htmlFor="new-silo-parent">상위 사일로</label>
          <select
            id="new-silo-parent"
            className="model-input"
            value={parentId}
            onChange={(e) => setParentId(e.target.value === '' ? '' : Number(e.target.value))}
          >
            <option value="">선택하세요</option>
            {parentOptions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>

        <div className="control-group">
          <label htmlFor="new-silo-name">하위 노드명</label>
          <input
            id="new-silo-name"
            type="text"
            className="model-input"
            value={name}
            placeholder="예: 노드13"
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
          <i className="fa-solid fa-plus" /> 하위 노드 증설
        </button>
      </div>
    </form>
  )
}
