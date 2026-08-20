import { DEPLOY_STRATEGY_META } from '@/constants/simulation'
import { useModelStore } from '@/store/useModelStore'
import type { DeployState, Deployment } from '@/types/simulation'

const STATE_LABEL: Record<DeployState, string> = {
  pending: '대기',
  deploying: '배포중',
  done: '완료',
  failed: '실패',
}

const STATE_CLASS: Record<DeployState, string> = {
  pending: 'dep-state-pending',
  deploying: 'dep-state-deploying',
  done: 'dep-state-done',
  failed: 'dep-state-failed',
}

function scopeText(d: Deployment): string {
  if (d.strategy === 'edge') return `사일로 ${d.targetSiloIds.length}곳`
  if (d.strategy === 'batch') return `전체 사일로 · 주기 ${d.intervalSec ?? 0}초`
  return '전체 사일로'
}

export function DeploymentTimeline() {
  const deployments = useModelStore((s) => s.deployments)
  const rollbackDeployment = useModelStore((s) => s.rollbackDeployment)

  return (
    <div className="deploy-timeline">
      <div className="deploy-card-head">
        <h4>
          <i className="fa-solid fa-list-check" /> 배포 상태
        </h4>
        <span className="desc">대기 → 배포중 → 완료 / 실패</span>
      </div>

      {deployments.length === 0 ? (
        <div className="deploy-empty">진행 중이거나 완료된 배포가 없습니다.</div>
      ) : (
        <ul className="deploy-list">
          {deployments.map((d) => {
            const meta = DEPLOY_STRATEGY_META[d.strategy]
            const inFlight = d.state === 'pending' || d.state === 'deploying'
            return (
              <li key={d.id} className="deploy-item">
                <span className={`dep-state-dot ${STATE_CLASS[d.state]}`} />
                <div className="deploy-item-main">
                  <span className="deploy-item-model">{d.modelLabel}</span>
                  <span className="deploy-item-meta">
                    <i className={`fa-solid ${meta.icon}`} /> {meta.label} · {scopeText(d)} · {d.ts}
                  </span>
                </div>
                <span className={`dep-state-badge ${STATE_CLASS[d.state]}`}>
                  {inFlight && <i className="fa-solid fa-spinner fa-spin" />} {STATE_LABEL[d.state]}
                </span>
                {d.state === 'done' && (
                  <button
                    type="button"
                    className="model-action rollback"
                    onClick={() => rollbackDeployment(d.id)}
                  >
                    <i className="fa-solid fa-rotate-left" /> 롤백
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
