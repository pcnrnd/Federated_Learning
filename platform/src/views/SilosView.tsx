import { useMemo, useState } from 'react'
import { SiloCard } from '@/components/silos/SiloCard'
import { SiloRegisterForm } from '@/components/silos/SiloRegisterForm'
import { useSiloStore } from '@/store/useSiloStore'

export function SilosView() {
  const silos = useSiloStore((s) => s.silos)
  const [showForm, setShowForm] = useState(false)

  const alertCount = useMemo(
    () =>
      silos.filter(
        (s) =>
          s.cpu >= s.thresholds.cpu || s.mem >= s.thresholds.mem || s.disk >= s.thresholds.disk,
      ).length,
    [silos],
  )

  return (
    <div className="tab-pane">
      <div className="glass-panel content-card full-card">
        <div className="card-header">
          <h3>
            <i className="fa-solid fa-warehouse" /> 사일로 리소스 모니터링 · 등록
          </h3>
          <span className="desc">
            Silo resource monitoring — CPU / memory / disk with threshold alerts &amp; registration.
          </span>
        </div>
        <div className="card-body">
          <div className="model-toolbar">
            <div className="silo-summary">
              <span className="lbl">등록 사일로</span>
              <span className="val">{silos.length}</span>
              <span className="lbl">임계 초과</span>
              <span className={`val${alertCount > 0 ? ' text-red' : ' text-green'}`}>{alertCount}</span>
            </div>
            <button type="button" className="btn-new-model" onClick={() => setShowForm((v) => !v)}>
              <i className={`fa-solid ${showForm ? 'fa-xmark' : 'fa-plus'}`} />{' '}
              {showForm ? '닫기' : '사일로 등록'}
            </button>
          </div>

          {showForm && <SiloRegisterForm onClose={() => setShowForm(false)} />}

          {silos.length === 0 ? (
            <div className="deploy-empty">등록된 사일로가 없습니다. “사일로 등록”으로 추가하세요.</div>
          ) : (
            <div className="silo-grid">
              {silos.map((silo) => (
                <SiloCard key={silo.id} silo={silo} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
