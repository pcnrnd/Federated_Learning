import { DeploymentTimeline } from './DeploymentTimeline'
import { StrategyForm } from './StrategyForm'
import { useDeployTarget } from './useDeployTarget'

/**
 * 6.2 후반부 — 모델 배포.
 * 패키징이 끝난 모델을 전략(일괄/실시간/선택)에 따라 사일로에 내보낸다.
 * 대상 모델 선택은 패키징 섹션이 담당하고, 여기서는 결과만 읽어 표시한다.
 */
export function DeploymentSection() {
  const { selectedModel, activeId, activePackage } = useDeployTarget()

  if (!selectedModel) {
    return <div className="deploy-empty">배포 가능한 모델이 없습니다. 먼저 모델을 등록하세요.</div>
  }

  const isPackaged = activePackage?.state === 'built'

  return (
    <div className="deploy-section">
      <div className="deploy-target-bar">
        <span className="deploy-target-label">배포 대상</span>
        <span className="deploy-target-name">
          {selectedModel.project} — {selectedModel.version}
        </span>
        <span className={`pkg-badge ${isPackaged ? 'pkg-badge-built' : 'pkg-badge-idle'}`}>
          {isPackaged ? '패키징 완료' : '패키징 필요'}
        </span>
      </div>

      {!isPackaged && (
        <div className="deploy-hint">
          <i className="fa-solid fa-circle-info" /> 위 “모델 패키징”에서 이미지를 먼저 빌드하세요.
        </div>
      )}

      <StrategyForm modelId={activeId} packaged={isPackaged} />
      <DeploymentTimeline />
    </div>
  )
}
