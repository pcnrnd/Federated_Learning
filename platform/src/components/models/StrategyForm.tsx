import { useState } from 'react'
import { DEPLOY_STRATEGY_META } from '@/constants/simulation'
import { useModelStore } from '@/store/useModelStore'
import { useSiloStore } from '@/store/useSiloStore'
import type { DeployStrategy } from '@/types/simulation'

interface StrategyFormProps {
  modelId: string
  packaged: boolean
}

const STRATEGIES: DeployStrategy[] = ['batch', 'realtime', 'edge']

export function StrategyForm({ modelId, packaged }: StrategyFormProps) {
  const createDeployment = useModelStore((s) => s.createDeployment)
  const silos = useSiloStore((s) => s.silos)

  const [strategy, setStrategy] = useState<DeployStrategy>('realtime')
  const [intervalSec, setIntervalSec] = useState(60)
  const [targetSiloIds, setTargetSiloIds] = useState<number[]>([])

  const toggleSilo = (id: number) => {
    setTargetSiloIds((prev) =>
      prev.includes(id) ? prev.filter((n) => n !== id) : [...prev, id],
    )
  }

  const edgeInvalid = strategy === 'edge' && targetSiloIds.length === 0
  const canDeploy = packaged && !edgeInvalid

  const handleDeploy = () => {
    if (!canDeploy) return
    createDeployment({ modelId, strategy, targetSiloIds, intervalSec })
    if (strategy === 'edge') setTargetSiloIds([])
  }

  return (
    <div className="deploy-card glass-panel">
      <div className="deploy-card-head">
        <h4>
          <i className="fa-solid fa-rocket" /> 배포 전략
        </h4>
      </div>

      <div className="strategy-options">
        {STRATEGIES.map((s) => {
          const meta = DEPLOY_STRATEGY_META[s]
          return (
            <button
              key={s}
              type="button"
              className={`strategy-option${strategy === s ? ' active' : ''}`}
              onClick={() => setStrategy(s)}
            >
              <i className={`fa-solid ${meta.icon}`} />
              <span className="strategy-label">{meta.label}</span>
              <span className="strategy-desc">{meta.desc}</span>
            </button>
          )
        })}
      </div>

      {strategy === 'batch' && (
        <div className="control-group">
          <label htmlFor="deploy-interval">일괄 배포 주기 (초)</label>
          <input
            id="deploy-interval"
            type="number"
            className="model-input"
            min={5}
            value={intervalSec}
            onChange={(e) => setIntervalSec(Number(e.target.value))}
          />
        </div>
      )}

      {strategy === 'edge' && (
        <div className="control-group">
          <label>대상 사일로 선택 ({targetSiloIds.length}곳)</label>
          <div className="edge-node-grid">
            {silos.map((silo) => (
              <button
                key={silo.id}
                type="button"
                className={`edge-node-chip${targetSiloIds.includes(silo.id) ? ' active' : ''}`}
                onClick={() => toggleSilo(silo.id)}
              >
                {silo.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {!packaged && (
        <p className="deploy-hint">
          <i className="fa-solid fa-circle-info" /> 먼저 패키징 빌드를 완료해야 배포할 수 있습니다.
        </p>
      )}

      <button
        type="button"
        className="btn btn-primary deploy-run-btn"
        disabled={!canDeploy}
        onClick={handleDeploy}
      >
        <i className="fa-solid fa-paper-plane" /> 배포 실행
      </button>
    </div>
  )
}
