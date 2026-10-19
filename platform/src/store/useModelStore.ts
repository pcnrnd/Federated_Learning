import { create } from 'zustand'
import {
  apiGet,
  apiMutation,
  apiPost,
  isLiveConfigured,
  type DeploymentEntryApi,
  type DeploymentRequestApi,
  type ModelEntryApi,
  type PackageRecordApi,
  type TrainingRoundSummary,
} from '@/api/client'
import { mapApiDeployments, mapModelsToVersions, parseModelKey } from '@/api/mappers'
import { liveModelRequest, mapLivePackages } from '@/lib/liveModels'
import { deploymentPayload, newDeploymentRequestId } from '@/lib/deploymentRequests'
import { DEPLOY_STRATEGY_META, DEPLOY_TIMINGS, RUNTIME_OPTIONS } from '@/constants/simulation'
import { useSiloStore } from '@/store/useSiloStore'
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
  LiveModelDraft,
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

/** 라이브 모드 여부 — 목 off + VITE_API_BASE 설정 */
function isLive(): boolean {
  return !useSimulationStore.getState().mockEnabled && isLiveConfigured()
}

async function refreshLiveCatalog(): Promise<void> {
  const epoch = useModelStore.getState().mutationEpoch
  const [models, deployments, packages] = await Promise.all([
    apiGet<ModelEntryApi[]>('/api/models'), apiGet<DeploymentEntryApi[]>('/api/deployments'),
    apiGet<PackageRecordApi[]>('/api/packaging'),
  ])
  if (isLive() && epoch === useModelStore.getState().mutationEpoch) {
    useModelStore.getState().applyLiveModels(mapModelsToVersions(models, deployments), mapApiDeployments(deployments), packages)
  }
}

async function liveModelMutation(operation: () => Promise<unknown>, label: string): Promise<boolean> {
  if (!isLive() || useModelStore.getState().liveModelPending) return false
  useModelStore.setState((state) => ({ liveModelPending: true, liveModelError: null, mutationEpoch: state.mutationEpoch + 1 }))
  let epoch = useModelStore.getState().mutationEpoch
  const current = () => isLive() && epoch === useModelStore.getState().mutationEpoch
  try {
    await operation()
    if (!current()) return false
    useModelStore.setState((state) => ({ mutationEpoch: state.mutationEpoch + 1 }))
    epoch = useModelStore.getState().mutationEpoch
    await refreshLiveCatalog()
    if (!current()) return false
    logToConsole('success', label)
    return true
  } catch (error) {
    if (!current()) return false
    const detail = error instanceof Error ? error.message : String(error)
    useModelStore.setState((state) => ({ liveModelError: detail, mutationEpoch: state.mutationEpoch + 1 }))
    epoch = useModelStore.getState().mutationEpoch
    logToConsole('error', `${label} 실패 — ${detail}`)
    return false
  } finally {
    if (epoch === useModelStore.getState().mutationEpoch) useModelStore.setState({ liveModelPending: false })
  }
}

/** 실서버 배포 생성 — 결과 반영은 다음 폴링 주기가 담당 */
async function liveCreateDeployment(input: DeployInput): Promise<void> {
  try {
    if (useModelStore.getState().liveModelPending) return
    const payload: DeploymentRequestApi = deploymentPayload(input, useSiloStore.getState().silos)
    const fingerprint = JSON.stringify(payload)
    const prior = useModelStore.getState().liveDeploymentRequests[input.modelId]
    const requestId = prior?.fingerprint === fingerprint ? prior.requestId : newDeploymentRequestId()
    useModelStore.setState((state) => ({ liveDeploymentRequests: { ...state.liveDeploymentRequests,
      [input.modelId]: { fingerprint, requestId } } }))
    const ok = await liveModelMutation(() => apiPost('/api/deployments', { ...payload, request_id: requestId }), '서버 배포 예약 반영')
    if (ok) useModelStore.setState((state) => {
      const { [input.modelId]: _completed, ...remaining } = state.liveDeploymentRequests
      return { liveDeploymentRequests: remaining }
    })
  } catch (error) {
    useModelStore.setState({ liveModelError: error instanceof Error ? error.message : String(error) })
  }
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
  /** 전략별 정확한 대상. 기존 deployModel 호출의 빈 배열만 전체 사일로로 해석한다. */
  targetSiloIds: number[]
  intervalSec?: number
  env?: Record<string, string>
  probeInputs?: unknown[]
  inferencePort?: number
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
  mutationEpoch: number
  liveModelDraft: LiveModelDraft
  liveModelResults: TrainingRoundSummary[]
  liveModelPending: boolean
  liveModelError: string | null
  liveDeploymentRequests: Record<string, { fingerprint: string; requestId: string }>
  patchLiveModelDraft: (patch: Partial<LiveModelDraft>) => void
  loadLiveModelResults: () => Promise<void>
  createLiveModel: () => Promise<boolean>

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
  retryDeployment: (id: string) => void
  stopDeployment: (id: string) => void

  /** 드리프트 경보 → 운영 모델 재학습 트리거 (신규 실험 버전 생성) */
  triggerRetrain: (modelId?: string) => void

  /** 목 off — 모델·패키징·배포 데이터를 비운다 */
  clearAll: () => void
  /** 목 on — 초기 시드로 복원한다 */
  reseed: () => void
  /** 라이브 모드 — 서버 폴링 결과(레지스트리·배포 기록)를 반영한다 */
  applyLiveModels: (models: ModelVersion[], deployments: Deployment[], packages?: PackageRecordApi[]) => void
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
  mutationEpoch: 0,
  liveModelDraft: { mode: 'training', round_id: '', version: '', name: '', weights_path: '' },
  liveModelResults: [],
  liveModelPending: false,
  liveModelError: null,
  liveDeploymentRequests: {},

  patchLiveModelDraft: (patch) => set((state) => ({ liveModelDraft: { ...state.liveModelDraft, ...patch } })),
  loadLiveModelResults: async () => {
    try {
      const results = await apiGet<TrainingRoundSummary[]>('/api/training-rounds?status=completed')
      if (isLive()) set({ liveModelResults: results.filter((round) => round.status === 'completed'
        && round.result?.format === 'ridge-v1' && !!round.result.result_id) })
    } catch (error) {
      set({ liveModelError: error instanceof Error ? error.message : String(error) })
    }
  },
  createLiveModel: async () => {
    try {
      const request = liveModelRequest(get().liveModelDraft)
      return await liveModelMutation(() => apiPost(request.endpoint, request.body), '실제 모델 등록 반영')
    } catch (error) {
      set({ liveModelError: error instanceof Error ? error.message : String(error) })
      return false
    }
  },

  setProjectFilter: (projectFilter) => set({ projectFilter }),
  setDeployTarget: (deployTargetId) => set({ deployTargetId }),

  clearAll: () =>
    set((state) => ({ models: [], packages: {}, deployments: [], deployTargetId: null,
        liveModelResults: [], liveModelError: null, liveModelPending: false, liveDeploymentRequests: {}, mutationEpoch: state.mutationEpoch + 1 })),

  applyLiveModels: (models, deployments, packages = []) =>
    set((state) => ({
      models,
      deployments,
      packages: mapLivePackages(packages),
      // 선택 모델이 서버 목록에서 사라졌으면 해제
      deployTargetId: models.some((m) => m.id === state.deployTargetId)
        ? state.deployTargetId
        : null,
    })),
  reseed: () => {
    const models = seedModels()
    set((state) => ({
      models,
      packages: seedPackages(models),
      deployments: [],
      deployTargetId: null,
      projectFilter: ALL_PROJECTS,
      liveModelPending: false, liveDeploymentRequests: {}, liveModelError: null, mutationEpoch: state.mutationEpoch + 1,
    }))
  },

  addModel: (input) => {
    if (isLive()) {
      logToConsole('system', '실서버 모드에서는 화면 등록을 지원하지 않습니다 — POST /api/models로 등록하세요.')
      return
    }
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
    if (isLive()) {
      // 운영 전환 = 실시간 전략으로 전체 사일로 배포 (배포됨 상태는 다음 폴링이 승격)
      void liveCreateDeployment({ modelId: id, strategy: 'realtime', targetSiloIds: [] })
      return
    }
    set((state) => ({ models: promoteToDeployed(state.models, target) }))
    logToConsole('success', `[${target.project}] ${target.version} 모델을 배포했습니다.`)
  },

  rollbackModel: (id) => {
    const target = get().models.find((m) => m.id === id)
    if (!target) return
    if (isLive()) {
      const current = get().deployments.find((entry) => entry.modelId === id && !entry.isSchedule && entry.previousDeploymentId)
      if (current) get().rollbackDeployment(current.id)
      else set({ liveModelError: '이 모델에 복원할 이전 정상 배포 설정이 없습니다' })
      return
    }
    set((state) => ({ models: promoteToDeployed(state.models, target) }))
    logToConsole('success', `[${target.project}] ${target.version} (으)로 롤백하여 재배포했습니다.`)
  },

  archiveModel: (id) => {
    const target = get().models.find((m) => m.id === id)
    if (!target) return
    if (isLive()) {
      const { name, version } = parseModelKey(id)
      void liveModelMutation(() => apiPost('/api/models/archive', { name, version }), '서버 모델 보관 반영')
      return
    }
    set((state) => ({
      models: state.models.map((m) => (m.id === id ? { ...m, status: 'archived' as ModelStatus } : m)),
    }))
    logToConsole('system', `[${target.project}] ${target.version} 모델을 보관 처리했습니다.`)
  },

  removeModel: (id) => {
    const target = get().models.find((m) => m.id === id)
    if (!target) return
    if (isLive()) {
      const { name, version } = parseModelKey(id)
      void liveModelMutation(() => apiMutation('DELETE', '/api/models', { name, version }), '서버 모델 삭제 반영')
      return
    }
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
    if (isLive()) {
      const { name, version } = parseModelKey(modelId)
      void liveModelMutation(() => apiPost('/api/packaging/request',
        { model_name: name, version, base_image: runtime }), '서버 이미지 빌드 요청 반영')
      return
    }
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
    if (isLive()) {
      void liveCreateDeployment(input)
      return
    }

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
    if (isLive()) {
      void liveModelMutation(() => apiPost(`/api/deployments/${id}/rollback`), '이전 정상 배포 복원 결과 반영')
      return
    }
    set((state) => ({ deployments: state.deployments.filter((d) => d.id !== id) }))
    logToConsole('error', `[${target.modelLabel}] 배포를 롤백하여 이전 운영 모델로 복원했습니다.`)
  },

  retryDeployment: (id) => { if (isLive()) void liveModelMutation(() => apiPost(`/api/deployments/${id}/retry`), '동일 배포 회차 재시도 반영') },
  stopDeployment: (id) => { if (isLive()) void liveModelMutation(() => apiPost(`/api/deployments/${id}/stop`), '실제 배포 정리 결과 반영') },

  triggerRetrain: (modelId?: string) => {
    if (isLive()) {
      logToConsole('system', '실서버 모드에서는 재학습 트리거를 지원하지 않습니다 — 학습 라운드를 서버에서 여세요.')
      return
    }
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
