import { create } from 'zustand'
import { DEPLOY_STRATEGY_META, DEPLOY_TIMINGS, RUNTIME_OPTIONS } from '@/constants/simulation'
import { useSimulationStore } from '@/store/useSimulationStore'
import type {
  Algorithm,
  DeployState,
  DeployStrategy,
  Deployment,
  LogKind,
  ModelPackage,
  ModelStatus,
  ModelVersion,
} from '@/types/simulation'

/** 모델 생성 폼에서 선택 가능한 프로젝트 목록 (목 데이터) */
export const MODEL_PROJECTS = [
  '프로젝트1',
  '프로젝트2',
  '프로젝트3',
] as const

/** 프로젝트 필터의 '전체' 가상 값 */
export const ALL_PROJECTS = 'all' as const

export type ProjectFilter = typeof ALL_PROJECTS | string

export interface NewModelInput {
  project: string
  version: string
  algorithm: Algorithm
  accuracy: number
  rounds: number
  note?: string
}

let modelSeq = 1
const nextModelId = (): string => `mdl-${modelSeq++}`

let deploySeq = 1
const nextDeployId = (): string => `dep-${deploySeq++}`

/** 공유 로그 콘솔(시뮬레이션 store)에 모델 이벤트를 기록 */
function logToConsole(kind: LogKind, message: string): void {
  useSimulationStore.getState().log(kind, message)
}

/**
 * 프로젝트명 + 버전 → 컨테이너 이미지 태그 생성.
 * 한글 등 ASCII 외 문자는 슬러그에서 제거되므로, 비거나 숫자로 시작하면 'proj-' 접두를 붙인다.
 * 예) '프로젝트1' v3.1 → 'proj-1:v3.1'.
 */
function buildImageTag(project: string, version: string): string {
  let slug = project
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
  if (!slug || /^[0-9]/.test(slug)) slug = `proj-${slug}`
  return `${slug}:${version}`
}

/** 'HH:MM:SS' 현재 시각 문자열 */
function nowTime(): string {
  return new Date().toTimeString().slice(0, 8)
}

/** 'v3.1' → 'v3.2' 형태로 마이너 버전 증가 (파싱 실패 시 -retrain 접미) */
function bumpVersion(version: string): string {
  const m = version.match(/^v?(\d+)\.(\d+)$/)
  if (!m) return `${version}-retrain`
  return `v${m[1]}.${Number(m[2]) + 1}`
}

export interface DeployInput {
  modelId: string
  strategy: DeployStrategy
  /** 선택 배포(edge)에서 대상 사일로 id 목록 */
  targetSiloIds: number[]
  intervalSec?: number
}

function seedModels(): ModelVersion[] {
  return [
    { id: nextModelId(), project: '프로젝트3', version: 'v3.1', status: 'deployed', accuracy: 94.7, algorithm: 'fedavg', rounds: 28, createdAt: '2026-06-01' },
    { id: nextModelId(), project: '프로젝트3', version: 'v3.0', status: 'experimental', accuracy: 93.2, algorithm: 'fedavg', rounds: 22, createdAt: '2026-05-18' },
    { id: nextModelId(), project: '프로젝트1', version: 'v2.3', status: 'deployed', accuracy: 92.4, algorithm: 'fedavg', rounds: 30, createdAt: '2026-05-28', note: '데이터 드리프트 보정 반영' },
    { id: nextModelId(), project: '프로젝트1', version: 'v2.2', status: 'experimental', accuracy: 90.1, algorithm: 'fedmedian', rounds: 25, createdAt: '2026-05-12' },
    { id: nextModelId(), project: '프로젝트1', version: 'v2.0', status: 'archived', accuracy: 87.6, algorithm: 'fedmedian', rounds: 20, createdAt: '2026-04-20' },
    { id: nextModelId(), project: '프로젝트2', version: 'v1.5', status: 'deployed', accuracy: 88.9, algorithm: 'secagg', rounds: 40, createdAt: '2026-05-22' },
    { id: nextModelId(), project: '프로젝트2', version: 'v1.4', status: 'archived', accuracy: 86.2, algorithm: 'secagg', rounds: 35, createdAt: '2026-04-30' },
  ]
}

export interface ModelStore {
  models: ModelVersion[]
  projectFilter: ProjectFilter
  /** modelId → 패키징 산출물 */
  packages: Record<string, ModelPackage>
  deployments: Deployment[]
  /** 패키징·배포 섹션에서 현재 선택된 대상 모델 (레지스트리에서 교차 설정) */
  deployTargetId: string | null

  setProjectFilter: (filter: ProjectFilter) => void
  setDeployTarget: (id: string | null) => void
  addModel: (input: NewModelInput) => void
  deployModel: (id: string) => void
  rollbackModel: (id: string) => void
  archiveModel: (id: string) => void
  removeModel: (id: string) => void

  buildPackage: (modelId: string, runtime: string) => void
  createDeployment: (input: DeployInput) => void
  rollbackDeployment: (id: string) => void

  /** 드리프트 경보 → 운영 모델 재학습 트리거 (신규 실험 버전 생성) */
  triggerRetrain: (modelId?: string) => void
}

/** 단일 배포 상태를 불변 갱신 */
function patchDeployment(
  deployments: Deployment[],
  id: string,
  state: DeployState,
): Deployment[] {
  return deployments.map((d) => (d.id === id ? { ...d, state } : d))
}

function seedPackages(models: ModelVersion[]): Record<string, ModelPackage> {
  const packages: Record<string, ModelPackage> = {}
  for (const m of models) {
    if (m.status !== 'deployed') continue
    packages[m.id] = {
      modelId: m.id,
      state: 'built',
      runtime: RUNTIME_OPTIONS[0],
      imageTag: buildImageTag(m.project, m.version),
      builtAt: m.createdAt,
    }
  }
  return packages
}

/** 동일 프로젝트의 기존 배포본을 실험 상태로 강등하고 대상 버전을 배포 상태로 승격 */
function promoteToDeployed(models: ModelVersion[], target: ModelVersion): ModelVersion[] {
  return models.map((m) => {
    if (m.id === target.id) return { ...m, status: 'deployed' as ModelStatus }
    if (m.project === target.project && m.status === 'deployed') {
      return { ...m, status: 'experimental' as ModelStatus }
    }
    return m
  })
}

const INITIAL_MODELS = seedModels()

export const useModelStore = create<ModelStore>((set, get) => ({
  models: INITIAL_MODELS,
  projectFilter: ALL_PROJECTS,
  packages: seedPackages(INITIAL_MODELS),
  deployments: [],
  deployTargetId: null,

  setProjectFilter: (projectFilter) => set({ projectFilter }),
  setDeployTarget: (deployTargetId) => set({ deployTargetId }),

  addModel: (input) => {
    const model: ModelVersion = {
      id: nextModelId(),
      project: input.project,
      version: input.version.trim(),
      status: 'experimental',
      accuracy: input.accuracy,
      algorithm: input.algorithm,
      rounds: input.rounds,
      createdAt: new Date().toISOString().slice(0, 10),
      ...(input.note?.trim() ? { note: input.note.trim() } : {}),
    }
    set((state) => ({ models: [model, ...state.models] }))
    logToConsole('server', `[${model.project}] ${model.version} 신규 모델 버전을 등록했습니다.`)
  },

  deployModel: (id) => {
    const target = get().models.find((m) => m.id === id)
    if (!target) return
    set((state) => ({ models: promoteToDeployed(state.models, target) }))
    logToConsole('success', `[${target.project}] ${target.version} 모델을 배포했습니다.`)
  },

  rollbackModel: (id) => {
    const target = get().models.find((m) => m.id === id)
    if (!target) return
    set((state) => ({ models: promoteToDeployed(state.models, target) }))
    logToConsole('success', `[${target.project}] ${target.version} (으)로 롤백하여 재배포했습니다.`)
  },

  archiveModel: (id) => {
    const target = get().models.find((m) => m.id === id)
    if (!target) return
    set((state) => ({
      models: state.models.map((m) => (m.id === id ? { ...m, status: 'archived' as ModelStatus } : m)),
    }))
    logToConsole('system', `[${target.project}] ${target.version} 모델을 보관 처리했습니다.`)
  },

  removeModel: (id) => {
    const target = get().models.find((m) => m.id === id)
    if (!target) return
    set((state) => {
      const { [id]: _removed, ...packages } = state.packages
      return {
        models: state.models.filter((m) => m.id !== id),
        packages,
        deployments: state.deployments.filter((d) => d.modelId !== id),
        deployTargetId: state.deployTargetId === id ? null : state.deployTargetId,
      }
    })
    logToConsole('error', `[${target.project}] ${target.version} 모델을 삭제했습니다.`)
  },

  buildPackage: (modelId, runtime) => {
    const target = get().models.find((m) => m.id === modelId)
    if (!target) return
    const imageTag = buildImageTag(target.project, target.version)

    set((state) => ({
      packages: {
        ...state.packages,
        [modelId]: { modelId, state: 'building', runtime, imageTag },
      },
    }))
    logToConsole('system', `[${target.project}] ${target.version} 컨테이너 패키징 빌드를 시작합니다. (${runtime})`)

    window.setTimeout(() => {
      set((state) => ({
        packages: {
          ...state.packages,
          [modelId]: { modelId, state: 'built', runtime, imageTag, builtAt: nowTime() },
        },
      }))
      logToConsole('success', `[${target.project}] ${target.version} 패키징 완료 — 이미지 ${imageTag} 생성.`)
    }, DEPLOY_TIMINGS.packageBuildMs)
  },

  createDeployment: (input) => {
    const target = get().models.find((m) => m.id === input.modelId)
    if (!target) return

    const id = nextDeployId()
    const modelLabel = `${target.project} ${target.version}`
    const meta = DEPLOY_STRATEGY_META[input.strategy]
    const deployment: Deployment = {
      id,
      modelId: input.modelId,
      modelLabel,
      strategy: input.strategy,
      targetSiloIds: input.strategy === 'edge' ? input.targetSiloIds : [],
      ...(input.strategy === 'batch' && input.intervalSec ? { intervalSec: input.intervalSec } : {}),
      state: 'pending',
      ts: nowTime(),
    }

    set((state) => ({ deployments: [deployment, ...state.deployments] }))

    const scope =
      input.strategy === 'edge'
        ? `사일로 ${input.targetSiloIds.length}곳`
        : input.strategy === 'batch'
          ? `전체 사일로 · 주기 ${input.intervalSec ?? 0}초`
          : '전체 사일로'
    logToConsole('system', `[${modelLabel}] ${meta.label} 요청 접수 (${scope}). 배포 대기열 등록.`)

    window.setTimeout(() => {
      set((state) => ({ deployments: patchDeployment(state.deployments, id, 'deploying') }))
      logToConsole('server', `[${modelLabel}] ${meta.label} 진행 중 — 모델 가중치 및 컨테이너 배포 전송...`)

      window.setTimeout(() => {
        set((state) => ({ deployments: patchDeployment(state.deployments, id, 'done') }))
        logToConsole('success', `[${modelLabel}] ${meta.label} 완료. 운영 반영됨.`)
      }, DEPLOY_TIMINGS.deployStepMs)
    }, DEPLOY_TIMINGS.deployStepMs)
  },

  rollbackDeployment: (id) => {
    const target = get().deployments.find((d) => d.id === id)
    if (!target) return
    set((state) => ({ deployments: state.deployments.filter((d) => d.id !== id) }))
    logToConsole('error', `[${target.modelLabel}] 배포를 롤백하여 이전 운영 모델로 복원했습니다.`)
  },

  triggerRetrain: (modelId?: string) => {
    const { models } = get()
    // modelId 지정 시 해당 모델, 미지정 시 첫 번째 배포 모델을 재학습 대상으로 선택
    const base =
      (modelId ? models.find((m) => m.id === modelId) : undefined) ??
      models.find((m) => m.status === 'deployed') ??
      models[0]
    if (!base) return

    const model: ModelVersion = {
      id: nextModelId(),
      project: base.project,
      version: bumpVersion(base.version),
      status: 'experimental',
      accuracy: base.accuracy,
      algorithm: base.algorithm,
      rounds: base.rounds,
      createdAt: new Date().toISOString().slice(0, 10),
      note: '데이터 드리프트 대응 재학습',
    }
    set((state) => ({ models: [model, ...state.models], projectFilter: base.project }))
    logToConsole(
      'system',
      `[드리프트 재학습] ${base.project} ${base.version} → ${model.version} 신규 실험 버전을 생성했습니다.`,
    )
    // 모델 탭으로 이동해 후속 배포를 유도
    useSimulationStore.getState().setActiveTab('models')
  },
}))
