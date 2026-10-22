import { DEPLOY_STRATEGY_META } from '@/constants/simulation'
import { useModelStore } from '@/store/useModelStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { DeployState, Deployment } from '@/types/simulation'

const STATE_LABEL: Record<DeployState, string> = {
  pending: '대기',
  deploying: '배포중',
  done: '완료',
  failed: '실패',
  stopped: '정지됨',
  rolled_back: '롤백됨',
}

const STATE_CLASS: Record<DeployState, string> = {
  pending: 'dep-state-pending',
  deploying: 'dep-state-deploying',
  done: 'dep-state-done',
  failed: 'dep-state-failed',
  stopped: 'dep-state-pending',
  rolled_back: 'dep-state-failed',
}

function scopeText(d: Deployment): string {
  if (d.targetNodeIds) return `${d.targetNodeIds.join(', ')}${d.strategy === 'batch' ? ` · 주기 ${d.intervalSec}초` : ''}`
  if (d.strategy === 'edge') return `사일로 ${d.targetSiloIds.length}곳`
  if (d.strategy === 'batch') return `전체 사일로 · 주기 ${d.intervalSec ?? 0}초`
  return '전체 사일로'
}

export function DeploymentTimeline() {
  const deployments = useModelStore((s) => s.deployments)
  const rollbackDeployment = useModelStore((s) => s.rollbackDeployment)
  const retryDeployment = useModelStore((s) => s.retryDeployment)
  const stopDeployment = useModelStore((s) => s.stopDeployment)
  const pending = useModelStore((s) => s.liveModelPending)
  const error = useModelStore((s) => s.liveModelError)
  const mock = useSimulationStore((s) => s.mockEnabled)

  return (
    <div className="deploy-timeline">
      <div className="deploy-card-head">
        <h4>
          <i className="fa-solid fa-list-check" /> 배포 상태
        </h4>
        <span className="desc">대기 → 배포중 → 완료 / 실패</span>
      </div>
      {error && <p role="alert">{error}</p>}

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
                  {d.isSchedule && <span className="desc">일정 {d.scheduleActive ? '활성' : '중지'} · 완료 {d.occurrence ?? 0}회 · 다음 예정 {d.nextDueAt ?? '없음'}</span>}
                  {d.imageId && <span className="desc">이미지 {d.imageId} · 실제 검증 {d.verifiedAt ?? '미완료'}</span>}
                  {!mock && !d.isSchedule && d.state === 'done' && !d.verifiedAt && <span className="desc">기존 기록 · 실제 예측 검증 미확인</span>}
                  {d.env && Object.keys(d.env).length > 0 && <span className="desc">환경변수: {Object.keys(d.env).join(', ')}</span>}
                  {d.error && <span role="alert" className="deploy-item-error">{d.error}{d.cleanupPending ? ' · 정리 확인 필요' : ''}</span>}
                  {d.targets && <ul>{Object.entries(d.targets).map(([node, target]) => <li key={node}>
                    {node}: {target.status === 'running' ? '기동·예측 확인' : target.status === 'failed' ? '실패' : '확인 대기'}
                    {target.endpoint && ` · ${target.endpoint}`}{target.error_code && ` · ${target.error_code}`}
                  </li>)}</ul>}
                </div>
                <span className={`dep-state-badge ${STATE_CLASS[d.state]}`}>
                  {inFlight && !d.isSchedule && <i className="fa-solid fa-spinner fa-spin" />} {d.isSchedule && d.scheduleActive ? '일정 대기' : STATE_LABEL[d.state]}
                </span>
                {!mock && d.state === 'failed' && !d.cleanupPending && <button type="button" className="model-action" disabled={pending}
                  onClick={() => retryDeployment(d.id)}>같은 회차 재시도</button>}
                {!mock && d.state !== 'stopped' && d.state !== 'rolled_back' && <button type="button" className="model-action" disabled={pending}
                  onClick={() => stopDeployment(d.id)}>{d.cleanupPending ? '정리 재시도' : '정지'}</button>}
                {d.state === 'done' && !d.isSchedule && (mock || (d.verifiedAt && d.previousDeploymentId)) && (
                  <button
                    type="button"
                    className="model-action rollback"
                    disabled={pending}
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
