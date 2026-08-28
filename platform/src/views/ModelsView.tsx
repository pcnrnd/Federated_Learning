import { DeploymentSection } from '@/components/models/DeploymentSection'
import { MODELS_DEPLOY_ANCHOR, ModelRegistry } from '@/components/models/ModelRegistry'
import { PackagingSection } from '@/components/models/PackagingSection'
import { scrollToElement } from '@/lib/scroll'

const MODELS_REGISTRY_ANCHOR = 'models-registry-card'
const MODELS_DEPLOY_RUN_ANCHOR = 'models-deploy-card'

export function ModelsView() {
  return (
    <div className="tab-pane">
      <nav className="section-anchor-nav" aria-label="모델 화면 내 이동">
        <button type="button" onClick={() => scrollToElement(MODELS_REGISTRY_ANCHOR)}>
          <i className="fa-solid fa-cubes" /> 버전관리
        </button>
        <button type="button" onClick={() => scrollToElement(MODELS_DEPLOY_ANCHOR)}>
          <i className="fa-solid fa-box" /> 패키징
        </button>
        <button type="button" onClick={() => scrollToElement(MODELS_DEPLOY_RUN_ANCHOR)}>
          <i className="fa-solid fa-truck-fast" /> 배포
        </button>
      </nav>

      <div id={MODELS_REGISTRY_ANCHOR} className="glass-panel content-card full-card">
        <div className="card-header">
          <h3>
            <i className="fa-solid fa-cubes" /> 연합 모델 버전관리 레지스트리
          </h3>
          <span className="desc">
            Model Registry — versioning, promotion &amp; rollback lifecycle.
          </span>
        </div>
        <div className="card-body">
          <ModelRegistry />
        </div>
      </div>

      <div id={MODELS_DEPLOY_ANCHOR} className="glass-panel content-card full-card">
        <div className="card-header">
          <h3>
            <i className="fa-solid fa-box" /> 모델 패키징
          </h3>
          <span className="desc">
            Packaging — container image build for the selected model version.
          </span>
        </div>
        <div className="card-body">
          <PackagingSection />
        </div>
      </div>

      <div id={MODELS_DEPLOY_RUN_ANCHOR} className="glass-panel content-card full-card">
        <div className="card-header">
          <h3>
            <i className="fa-solid fa-truck-fast" /> 모델 배포
          </h3>
          <span className="desc">
            Deployment — batch / realtime / edge strategies with rollback.
          </span>
        </div>
        <div className="card-body">
          <DeploymentSection />
        </div>
      </div>
    </div>
  )
}
