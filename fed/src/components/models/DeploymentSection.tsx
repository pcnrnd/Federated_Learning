import { useMemo } from 'react'
import { useModelStore } from '@/store/useModelStore'
import { DeploymentTimeline } from './DeploymentTimeline'
import { PackagingCard } from './PackagingCard'
import { StrategyForm } from './StrategyForm'

/**
 * 6.2 모델 패키징·배포 관리 섹션.
 * 배포 가능한(보관 제외) 모델 1개를 선택해 패키징 → 전략 선택 → 배포 실행한다.
 * 선택 대상은 store(deployTargetId)에 두어 레지스트리에서 교차 선택할 수 있게 한다.
 */
export function DeploymentSection() {
  const models = useModelStore((s) => s.models)
  const packages = useModelStore((s) => s.packages)
  const deployTargetId = useModelStore((s) => s.deployTargetId)
  const setDeployTarget = useModelStore((s) => s.setDeployTarget)

  const deployable = useMemo(() => models.filter((m) => m.status !== 'archived'), [models])

  // 선택된 모델이 없거나 삭제/보관되면 첫 배포 가능 모델로 폴백
  const selectedModel =
    deployable.find((m) => m.id === deployTargetId) ?? deployable[0] ?? null
  const activeId = selectedModel?.id ?? ''
  const activePackage = activeId ? packages[activeId] : undefined

  if (!selectedModel) {
    return (
      <div className="deploy-empty">
        배포 가능한 모델이 없습니다. 먼저 모델을 등록하세요.
      </div>
    )
  }

  return (
    <div className="deploy-section">
      <div className="deploy-model-picker control-group">
        <label htmlFor="deploy-model-select">배포 대상 모델</label>
        <div className="select-wrapper">
          <select
            id="deploy-model-select"
            value={activeId}
            onChange={(e) => setDeployTarget(e.target.value)}
          >
            {deployable.map((m) => (
              <option key={m.id} value={m.id}>
                {m.project} — {m.version} ({m.status === 'deployed' ? '배포됨' : '실험'})
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="deploy-grid">
        <PackagingCard model={selectedModel} pkg={activePackage} />
        <StrategyForm modelId={activeId} packaged={activePackage?.state === 'built'} />
      </div>

      <DeploymentTimeline />
    </div>
  )
}
