import { DeploymentSection } from '@/components/models/DeploymentSection'
import { MODELS_DEPLOY_ANCHOR, ModelRegistry } from '@/components/models/ModelRegistry'
import { scrollToElement } from '@/lib/scroll'

const MODELS_REGISTRY_ANCHOR = 'models-registry-card'

export function ModelsView() {
  return (
    <div className="tab-pane">
      <nav className="section-anchor-nav" aria-label="모델 화면 내 이동">
        <button type="button" onClick={() => scrollToElement(MODELS_REGISTRY_ANCHOR)}>
          <i className="fa-solid fa-cubes" /> 버전관리
        </button>
        <button type="button" onClick={() => scrollToElement(MODELS_DEPLOY_ANCHOR)}>
          <i className="fa-solid fa-truck-fast" /> 패키징·배포
        </button>
      </nav>

      <div id={MODELS_REGISTRY_ANCHOR} className="glass-panel content-card full-card">
        <div className="card-header">
          <h3>
            <i className="fa-solid fa-cubes" /> 연합 모델 버전관리 레지스트리
          </h3>
          <span className="desc">
            Model Registry — packaging, versioning, deployment &amp; rollback lifecycle.
          </span>
        </div>
        <div className="card-body">
          <ModelRegistry />
        </div>
      </div>

      <div id={MODELS_DEPLOY_ANCHOR} className="glass-panel content-card full-card">
        <div className="card-header">
          <h3>
            <i className="fa-solid fa-truck-fast" /> 모델 패키징 · 배포 관리
          </h3>
          <span className="desc">
            Packaging &amp; deployment — batch / realtime / edge strategies with rollback.
          </span>
        </div>
        <div className="card-body">
          <DeploymentSection />
        </div>
      </div>
    </div>
  )
}
