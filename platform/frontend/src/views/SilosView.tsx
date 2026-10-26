import { useMemo, useState } from 'react'
import { SiloCard } from '@/components/silos/SiloCard'
import { SiloRegisterForm } from '@/components/silos/SiloRegisterForm'
import { useSiloStore } from '@/store/useSiloStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import { exceedsThreshold, siloActionKey, siloDraftKey } from '@/lib/siloResources'
import { SiloGroups } from '@/components/silos/SiloGroups'
import { SiloResourceHistory } from '@/components/silos/SiloResourceHistory'

export function SilosView() {
  const silos = useSiloStore((s) => s.silos)
  const error = useSiloStore((s) => s.mutationError)
  const pollError = useSiloStore((s) => s.pollError)
  const isLive = !useSimulationStore((s) => s.mockEnabled)
  const [showForm, setShowForm] = useState(false)

  const alertCount = useMemo(
    () =>
      silos.filter(
        (s) =>
          exceedsThreshold(s.cpu, s.thresholds.cpu) || exceedsThreshold(s.mem, s.thresholds.mem) || exceedsThreshold(s.disk, s.thresholds.disk),
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
          {error && <p role="alert" className="text-red">서버 변경 실패: {error}</p>}
          {isLive && pollError && <p role="alert" className="text-red">서버 연결 실패: {pollError}. 값은 마지막 관측이며 현재 판정을 확인할 수 없습니다.</p>}
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
                <SiloCard key={siloDraftKey(siloActionKey(silo))} silo={silo} />
              ))}
            </div>
          )}
          <SiloGroups />
          <SiloResourceHistory />
        </div>
      </div>
    </div>
  )
}
