import { useMemo, useState } from 'react'
import { ALGORITHM_LABEL } from '@/constants/simulation'
import { formatPercent } from '@/lib/format'
import { scrollToElement } from '@/lib/scroll'
import { ALL_PROJECTS, MODEL_PROJECTS, useModelStore } from '@/store/useModelStore'
import type { ModelStatus, ModelVersion } from '@/types/simulation'
import { NewModelForm } from './NewModelForm'

/** 패키징·배포 섹션 카드의 DOM id (앵커 네비/교차 스크롤용) */
export const MODELS_DEPLOY_ANCHOR = 'models-deploy-card'

const STATUS_LABEL: Record<ModelStatus, string> = {
  deployed: '배포됨',
  experimental: '실험',
  archived: '보관',
}

const STATUS_CLASS: Record<ModelStatus, string> = {
  deployed: 'model-badge-deployed',
  experimental: 'model-badge-experimental',
  archived: 'model-badge-archived',
}

function RowActions({ model }: { model: ModelVersion }) {
  const deployModel = useModelStore((s) => s.deployModel)
  const rollbackModel = useModelStore((s) => s.rollbackModel)
  const archiveModel = useModelStore((s) => s.archiveModel)
  const removeModel = useModelStore((s) => s.removeModel)
  const setDeployTarget = useModelStore((s) => s.setDeployTarget)

  // 레지스트리 → 패키징·배포 섹션으로 흐름 연결: 대상 선택 후 섹션으로 스크롤
  const handlePackaging = () => {
    setDeployTarget(model.id)
    scrollToElement(MODELS_DEPLOY_ANCHOR)
  }

  return (
    <div className="model-row-actions">
      {model.status === 'experimental' && (
        <button type="button" className="model-action deploy" onClick={() => deployModel(model.id)}>
          <i className="fa-solid fa-circle-check" /> 운영 전환
        </button>
      )}
      {model.status === 'archived' && (
        <button type="button" className="model-action rollback" onClick={() => rollbackModel(model.id)}>
          <i className="fa-solid fa-rotate-left" /> 롤백
        </button>
      )}
      {model.status !== 'archived' && (
        <button type="button" className="model-action packaging" onClick={handlePackaging}>
          <i className="fa-solid fa-truck-fast" /> 패키징·배포
        </button>
      )}
      {model.status !== 'archived' && (
        <button type="button" className="model-action archive" onClick={() => archiveModel(model.id)}>
          <i className="fa-solid fa-box-archive" /> 보관
        </button>
      )}
      <button type="button" className="model-action remove" onClick={() => removeModel(model.id)}>
        <i className="fa-solid fa-trash" /> 삭제
      </button>
    </div>
  )
}

export function ModelRegistry() {
  const models = useModelStore((s) => s.models)
  const projectFilter = useModelStore((s) => s.projectFilter)
  const setProjectFilter = useModelStore((s) => s.setProjectFilter)
  const [showForm, setShowForm] = useState(false)

  const visibleModels = useMemo(
    () => (projectFilter === ALL_PROJECTS ? models : models.filter((m) => m.project === projectFilter)),
    [models, projectFilter],
  )

  const summary = useMemo(() => {
    const total = visibleModels.length
    const deployed = visibleModels.filter((m) => m.status === 'deployed').length
    const experimental = visibleModels.filter((m) => m.status === 'experimental').length
    const avgAccuracy = total > 0 ? visibleModels.reduce((sum, m) => sum + m.accuracy, 0) / total : 0
    return { total, deployed, experimental, avgAccuracy }
  }, [visibleModels])

  const filterOptions: Array<{ value: string; label: string }> = [
    { value: ALL_PROJECTS, label: '전체' },
    ...MODEL_PROJECTS.map((p) => ({ value: p, label: p })),
  ]

  const defaultProject = projectFilter === ALL_PROJECTS ? MODEL_PROJECTS[0] : projectFilter

  return (
    <div className="model-registry">
      <div className="model-toolbar">
        <div className="filter-group">
          {filterOptions.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`filter-btn${projectFilter === opt.value ? ' active' : ''}`}
              onClick={() => setProjectFilter(opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <button type="button" className="btn-new-model" onClick={() => setShowForm((v) => !v)}>
          <i className={`fa-solid ${showForm ? 'fa-xmark' : 'fa-plus'}`} />{' '}
          {showForm ? '닫기' : '새 모델 생성'}
        </button>
      </div>

      {showForm && <NewModelForm defaultProject={defaultProject} onClose={() => setShowForm(false)} />}

      <div className="model-stat-grid">
        <div className="model-stat-card">
          <span className="lbl">전체 버전</span>
          <span className="val">{summary.total}</span>
        </div>
        <div className="model-stat-card">
          <span className="lbl">배포 중</span>
          <span className="val text-green">{summary.deployed}</span>
        </div>
        <div className="model-stat-card">
          <span className="lbl">실험</span>
          <span className="val text-cyan">{summary.experimental}</span>
        </div>
        <div className="model-stat-card">
          <span className="lbl">평균 정확도</span>
          <span className="val text-purple">{formatPercent(summary.avgAccuracy, 1)}</span>
        </div>
      </div>

      <div className="model-table-wrapper">
        <table className="model-table">
          <thead>
            <tr>
              <th>프로젝트</th>
              <th>버전</th>
              <th>상태</th>
              <th>합산 알고리즘</th>
              <th className="ta-right">정확도</th>
              <th className="ta-right">라운드</th>
              <th>생성일</th>
              <th className="ta-right">액션</th>
            </tr>
          </thead>
          <tbody>
            {visibleModels.map((model) => (
              <tr key={model.id}>
                <td className="model-project-cell">{model.project}</td>
                <td className="model-version-cell">
                  {model.version}
                  {model.note && <span className="model-note" title={model.note}>{model.note}</span>}
                </td>
                <td>
                  <span className={`model-badge ${STATUS_CLASS[model.status]}`}>
                    {STATUS_LABEL[model.status]}
                  </span>
                </td>
                <td className="model-algo-cell">{ALGORITHM_LABEL[model.algorithm]}</td>
                <td className="ta-right text-cyan">{formatPercent(model.accuracy)}</td>
                <td className="ta-right">{model.rounds}</td>
                <td className="model-date-cell">{model.createdAt}</td>
                <td>
                  <RowActions model={model} />
                </td>
              </tr>
            ))}
            {visibleModels.length === 0 && (
              <tr>
                <td colSpan={8} className="model-empty">
                  등록된 모델 버전이 없습니다. “새 모델 생성”으로 추가하세요.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
