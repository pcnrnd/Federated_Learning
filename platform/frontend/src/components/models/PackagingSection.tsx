import { useModelStore } from '@/store/useModelStore'
import { useDeployTarget } from './useDeployTarget'
import { PackagingCard } from './PackagingCard'

/**
 * 6.2 전반부 — 모델 패키징.
 * 배포 대상 모델을 고르고 컨테이너 이미지를 빌드하는 단계까지만 담당한다.
 * 선택은 store(deployTargetId)에 있어 레지스트리·배포 섹션과 공유된다.
 */
export function PackagingSection() {
  const setDeployTarget = useModelStore((s) => s.setDeployTarget)
  const { deployable, selectedModel, activeId, activePackage } = useDeployTarget()

  if (!selectedModel) {
    return <div className="deploy-empty">패키징할 모델이 없습니다. 먼저 모델을 등록하세요.</div>
  }

  return (
    <div className="deploy-section">
      <div className="deploy-model-picker control-group">
        <label htmlFor="deploy-model-select">대상 모델</label>
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

      <PackagingCard model={selectedModel} pkg={activePackage} />
    </div>
  )
}
