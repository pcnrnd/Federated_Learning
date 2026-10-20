import { useEffect } from 'react'
import {
  apiGet, isLiveConfigured, type CleaningJobApi, type DeploymentEntryApi,
  type MetricSample, type ModelEntryApi, type PackageRecordApi, type Paginated,
  type ResourceLimit, type ResourceUsageSummary, type TrainingRoundSummary,
  type SiloRegistrationApi, type SiloGroupApi,
} from '@/api/client'
import { mapApiDeployments, mapCleaningJobs, mapMetricsToChartPoints,
  mapMetricsToMonitorPoints, mapModelsToVersions } from '@/api/mappers'
import { dataSourceGuard } from '@/lib/dataSource'
import { mapRegisteredSilos } from '@/lib/siloResources'
import { useDataStore } from '@/store/useDataStore'
import { useModelStore } from '@/store/useModelStore'
import { useSiloStore } from '@/store/useSiloStore'
import { useSimulationStore } from '@/store/useSimulationStore'

const query = (metric: string) => `/api/monitoring/metrics?metric=${metric}&limit=500`

/** 한 API 실패가 다른 화면의 실제 기록을 숨기지 않는다. 실패를 빈 데이터로 대체하지 않는다. */
export async function pollLiveData(): Promise<void> {
  const current = dataSourceGuard(false)
  if (!current() || !isLiveConfigured()) return
  const siloEpoch = useSiloStore.getState().mutationEpoch
  const modelEpoch = useModelStore.getState().mutationEpoch
  const dataEpoch = useDataStore.getState().mutationEpoch
  const cleaningPending = useDataStore.getState().livePending
  const errors: string[] = []
  const read = async <T,>(path: string): Promise<T | undefined> => {
    try {
      const value = await apiGet<T>(path)
      const list = path.includes('/metrics?') ? (value as { items?: unknown } | null)?.items : value
      if (!Array.isArray(list)) throw new Error(`GET ${path} → 목록 응답 형식 불일치`)
      return value
    }
    catch (error) { errors.push(error instanceof Error ? error.message : String(error)); return undefined }
  }
  const [usage, limits, accuracy, throughput, latency, rounds, cleaning, models, deployments, registrations, groups, packages] = await Promise.all([
    read<ResourceUsageSummary[]>('/api/resources/usage'), read<ResourceLimit[]>('/api/resources/limits'),
    read<Paginated<MetricSample>>(query('accuracy')), read<Paginated<MetricSample>>(query('throughput_rps')),
    read<Paginated<MetricSample>>(query('latency_ms')), read<TrainingRoundSummary[]>('/api/training-rounds'),
    read<CleaningJobApi[]>('/api/cleaning-jobs'), read<ModelEntryApi[]>('/api/models'),
    read<DeploymentEntryApi[]>('/api/deployments'), read<SiloRegistrationApi[]>('/api/silos'),
    read<SiloGroupApi[]>('/api/silo-groups'), read<PackageRecordApi[]>('/api/packaging'),
  ])
  if (!current()) return
  if (registrations && siloEpoch === useSiloStore.getState().mutationEpoch) {
    const currentGroups = groups ?? useSiloStore.getState().groups
    useSiloStore.getState().applyLiveSilos(mapRegisteredSilos(registrations, usage ?? [], limits ?? [], currentGroups), currentGroups)
  }
  if (cleaning && !cleaningPending && !useDataStore.getState().livePending && dataEpoch === useDataStore.getState().mutationEpoch) {
    const mapped = mapCleaningJobs(cleaning)
    useDataStore.getState().applyLiveCleaning(mapped.dataBySilo, mapped.jobs)
  }
  if (models && modelEpoch === useModelStore.getState().mutationEpoch) {
    const prior = useModelStore.getState()
    const versions = mapModelsToVersions(models, deployments ?? []).map((model) => deployments ? model
      : { ...model, status: prior.models.find((m) => m.id === model.id)?.status ?? model.status })
    prior.applyLiveModels(versions, deployments ? mapApiDeployments(deployments) : prior.deployments, packages)
  }
  const store = useSimulationStore.getState()
  store.applyLiveSnapshot({
    ...(accuracy ? { chartPoints: mapMetricsToChartPoints(accuracy.items) } : {}),
    ...(throughput && latency ? { monitorPoints: mapMetricsToMonitorPoints(throughput.items, latency.items) } : {}),
    ...(rounds ? { currentRound: rounds.length } : {}),
  })
  if (errors.length) {
    const detail = errors.join(' · ')
    if (store.liveError !== detail) store.log('error', `실서버 조회 실패 — ${detail}`)
    store.setLiveStatus('error', detail)
    if (!registrations || !usage || !limits || !groups) useSiloStore.getState().recordPollFailure(detail)
  } else {
    store.setLiveStatus(registrations?.length || models?.length || rounds?.length || cleaning?.length ? 'ready' : 'empty')
  }
}

export function useLivePolling(): void {
  const demo = useSimulationStore((s) => s.mockEnabled)
  const generation = useSimulationStore((s) => s.dataGeneration)
  useEffect(() => {
    if (demo || !isLiveConfigured()) return
    let pending = false
    let cancelled = false
    const poll = async () => {
      if (pending || cancelled) return
      pending = true
      useSiloStore.getState().refreshObservationState()
      try { await pollLiveData() } finally { pending = false }
    }
    void poll()
    const timer = window.setInterval(() => { void poll() }, 5000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [demo, generation])
}
