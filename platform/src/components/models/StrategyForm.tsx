import { useState } from 'react'
import { DEPLOY_STRATEGY_META } from '@/constants/simulation'
import { siloActionKey, siloDraftKey } from '@/lib/siloResources'
import { parseDeploymentEnv } from '@/lib/deploymentRequests'
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
  const latest = useModelStore((s) => s.deployments.find((d) => d.modelId === modelId && d.targetNodeIds))
  const pending = useModelStore((s) => s.liveModelPending)
  const serverError = useModelStore((s) => s.liveModelError)

  const [strategy, setStrategy] = useState<DeployStrategy>('realtime')
  const [intervalSec, setIntervalSec] = useState(60)
  const [targetSiloIds, setTargetSiloIds] = useState<number[]>([])
  const [envText, setEnvText] = useState('')
  const [probeText, setProbeText] = useState('')
  const [inferencePort, setInferencePort] = useState(8501)
  const [draftError, setDraftError] = useState<string | null>(null)

  const toggleSilo = (id: number) => {
    setTargetSiloIds((prev) =>
      prev.includes(id) ? prev.filter((n) => n !== id) : [...prev, id],
    )
  }

  const canDeploy = packaged && targetSiloIds.length > 0 && !pending

  const loadSaved = () => {
    if (!latest) return
    setStrategy(latest.strategy)
    setIntervalSec(latest.intervalSec ?? 60)
    setTargetSiloIds(silos.filter((silo) => latest.targetNodeIds?.includes(silo.serverId ?? silo.name)).map((silo) => silo.id))
    setEnvText(Object.entries(latest.env ?? {}).map(([key, value]) => `${key}=${value}`).join('\n'))
    setProbeText(latest.probeInputs ? JSON.stringify(latest.probeInputs) : '')
    setInferencePort(latest.inferencePort ?? 8501)
    setDraftError(null)
  }

  const handleDeploy = () => {
    if (!canDeploy) return
    try {
      const probeInputs: unknown = probeText.trim() ? JSON.parse(probeText) : undefined
      if (probeInputs !== undefined && (!Array.isArray(probeInputs) || probeInputs.length === 0)) {
        throw new Error('예측 확인 입력은 비어 있지 않은 JSON 배열로 입력하세요')
      }
      if (strategy === 'batch' && (!Number.isInteger(intervalSec) || intervalSec < 1)) {
        throw new Error('배포 주기는 양의 정수 초로 입력하세요')
      }
      createDeployment({ modelId, strategy, targetSiloIds, intervalSec,
        env: parseDeploymentEnv(envText), probeInputs: probeInputs as unknown[] | undefined, inferencePort })
      setDraftError(null)
    } catch (error) {
      setDraftError(error instanceof Error ? error.message : '배포 설정을 확인하세요')
    }
  }

  return (
    <div className="deploy-card glass-panel">
      <div className="deploy-card-head">
        <h4>
          <i className="fa-solid fa-rocket" /> 배포 전략
        </h4>
        {latest && <button type="button" className="model-action" disabled={pending} onClick={loadSaved}>서버 설정 불러오기</button>}
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
            min={1}
            value={intervalSec}
            onChange={(e) => setIntervalSec(Number(e.target.value))}
          />
        </div>
      )}

      <div className="control-group">
          <label>대상 사일로 선택 ({targetSiloIds.length}곳)</label>
          <div className="edge-node-grid">
            {silos.map((silo) => (
              <button
                key={siloDraftKey(siloActionKey(silo))}
                type="button"
                className={`edge-node-chip${targetSiloIds.includes(silo.id) ? ' active' : ''}`}
                onClick={() => toggleSilo(silo.id)}
              >
                {silo.name}
              </button>
            ))}
          </div>
      </div>

      <div className="control-group">
        <label htmlFor="deploy-port">컨테이너 내부 포트 (호스트 포트는 자동 할당)</label>
        <input id="deploy-port" className="model-input" type="number" min={1} max={65535} value={inferencePort}
          onChange={(event) => setInferencePort(Number(event.target.value))} />
      </div>

      <div className="control-group">
        <label htmlFor="deploy-env">환경변수 (한 줄에 KEY=value)</label>
        <textarea id="deploy-env" className="model-input" value={envText} rows={3}
          onChange={(event) => setEnvText(event.target.value)} autoComplete="off" />
      </div>
      <div className="control-group">
        <label htmlFor="deploy-probe">예측 확인 입력 (선택, JSON 배열)</label>
        <textarea id="deploy-probe" className="model-input" value={probeText} rows={2}
          onChange={(event) => setProbeText(event.target.value)} />
        <p className="deploy-hint">입력 스키마가 없는 모델은 확인 입력이 필요합니다. 일괄 배포의 첫 실행은 지정 주기 후입니다.</p>
      </div>
      {(draftError || serverError) && <p role="alert" className="deploy-hint">{draftError ?? serverError}</p>}

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
        <i className={`fa-solid ${pending ? 'fa-spinner fa-spin' : 'fa-paper-plane'}`} /> 배포 예약
      </button>
    </div>
  )
}
