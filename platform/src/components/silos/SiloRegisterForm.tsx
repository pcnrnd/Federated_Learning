import { useSiloStore } from '@/store/useSiloStore'
import { useSimulationStore } from '@/store/useSimulationStore'

interface SiloRegisterFormProps {
  onClose: () => void
}

export function SiloRegisterForm({ onClose }: SiloRegisterFormProps) {
  const addSilo = useSiloStore((s) => s.addSilo)
  const silos = useSiloStore((s) => s.silos)
  const pending = useSiloStore((s) => s.pending)
  const isLive = !useSimulationStore((s) => s.mockEnabled)

  // 계층 깊이는 2단 — 상위로 지정할 수 있는 건 1단 사일로뿐이다
  const parentOptions = silos.filter((s) => s.parentId === undefined)

  const { name, siloId, endpoint, collectIntervalSec, parentId } = useSiloStore((s) => s.registrationDraft)
  const patchRegistration = useSiloStore((s) => s.patchRegistration)
  const clearRegistration = useSiloStore((s) => s.clearRegistration)

  const canSubmit = name.trim().length > 0 && endpoint.trim().length > 0
    && collectIntervalSec >= 5 && collectIntervalSec <= 86400
    && (isLive ? /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(siloId) : parentId !== '')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    // canSubmit이 parentId !== '' 를 포함하므로 여기서 parentId는 number로 좁혀진다
    if (!canSubmit) return
    const saved = await addSilo({ name, endpoint, collectIntervalSec, siloId, ...(parentId !== '' ? { parentId } : {}) })
    if (saved) { clearRegistration(); onClose() }
  }

  return (
    <form className="model-form glass-panel" onSubmit={handleSubmit}>
      <div className="model-form-grid">
        {isLive ? <div className="control-group">
          <label htmlFor="new-silo-id">사일로 식별자</label>
          <input id="new-silo-id" className="model-input" value={siloId} placeholder="예: silo-7" onChange={(e) => patchRegistration({ siloId: e.target.value })} />
        </div> : <div className="control-group">
          <label htmlFor="new-silo-parent">상위 사일로</label>
          <select
            id="new-silo-parent"
            className="model-input"
            value={parentId}
            onChange={(e) => patchRegistration({ parentId: e.target.value === '' ? '' : Number(e.target.value) })}
          >
            <option value="">선택하세요</option>
            {parentOptions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>}

        <div className="control-group">
          <label htmlFor="new-silo-name">사일로명</label>
          <input
            id="new-silo-name"
            type="text"
            className="model-input"
            value={name}
            placeholder="예: 노드13"
            onChange={(e) => patchRegistration({ name: e.target.value })}
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
            onChange={(e) => patchRegistration({ endpoint: e.target.value })}
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
            onChange={(e) => patchRegistration({ collectIntervalSec: Number(e.target.value) })}
          />
        </div>
      </div>

      <div className="model-form-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          취소
        </button>
        <button type="submit" className="btn btn-primary" disabled={!canSubmit || pending}>
          <i className="fa-solid fa-plus" /> {pending ? '저장 중' : '사일로 등록'}
        </button>
      </div>
    </form>
  )
}
