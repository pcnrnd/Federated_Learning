import { useEffect } from 'react'
import {
  apiGet,
  isLiveConfigured,
  API_BASE,
  type CleaningJobApi,
  type DeploymentEntryApi,
  type MetricSample,
  type ModelEntryApi,
  type Paginated,
  type ResourceLimit,
  type ResourceUsageSummary,
  type TrainingRoundSummary,
} from '@/api/client'
import {
  mapApiDeployments,
  mapCleaningJobs,
  mapMetricsToChartPoints,
  mapMetricsToMonitorPoints,
  mapModelsToVersions,
  mapUsageToSilos,
} from '@/api/mappers'
import { useDataStore } from '@/store/useDataStore'
import { useModelStore } from '@/store/useModelStore'
import { useSiloStore } from '@/store/useSiloStore'
import { useSimulationStore } from '@/store/useSimulationStore'

const LIVE_POLL_INTERVAL_MS = 5000
const METRIC_QUERY_LIMIT = 500

/**
 * 라이브 모드 폴링 (P0 — 읽기 전용 3종: 리소스 / 성능 지표 / 라운드 상태).
 * 목 데이터가 꺼져 있고 `VITE_API_BASE`가 설정된 동안만 5초 주기로 돈다.
 * 계약: docs/specs/2026-08-21-p0-api-contract.md
 */
export function useLivePolling(): void {
  const mockEnabled = useSimulationStore((s) => s.mockEnabled)
  const isLive = !mockEnabled && isLiveConfigured()

  useEffect(() => {
    if (!isLive) return

    // 연속 실패 시 로그 스팸을 막고, 복구 시에만 다시 알린다
    let wasHealthy: boolean | null = null

    const poll = async () => {
      const store = useSimulationStore.getState()
      try {
        const [usage, limits, accuracy, throughput, latency, rounds, cleaningJobs, models, deployments] = await Promise.all([
          apiGet<ResourceUsageSummary[]>('/api/resources/usage'),
          apiGet<ResourceLimit[]>('/api/resources/limits'),
          apiGet<Paginated<MetricSample>>(
            `/api/monitoring/metrics?metric=accuracy&limit=${METRIC_QUERY_LIMIT}`,
          ),
          apiGet<Paginated<MetricSample>>(
            `/api/monitoring/metrics?metric=throughput_rps&limit=${METRIC_QUERY_LIMIT}`,
          ),
          apiGet<Paginated<MetricSample>>(
            `/api/monitoring/metrics?metric=latency_ms&limit=${METRIC_QUERY_LIMIT}`,
          ),
          apiGet<TrainingRoundSummary[]>('/api/training-rounds'),
          apiGet<CleaningJobApi[]>('/api/cleaning-jobs'),
          apiGet<ModelEntryApi[]>('/api/models'),
          apiGet<DeploymentEntryApi[]>('/api/deployments'),
        ])

        useSiloStore.getState().setSilos(mapUsageToSilos(usage, limits))

        const cleaning = mapCleaningJobs(cleaningJobs)
        useDataStore.getState().applyLiveCleaning(cleaning.dataBySilo, cleaning.jobs)

        useModelStore
          .getState()
          .applyLiveModels(mapModelsToVersions(models, deployments), mapApiDeployments(deployments))

        const chartPoints = mapMetricsToChartPoints(accuracy.items)
        const monitorPoints = mapMetricsToMonitorPoints(throughput.items, latency.items)
        const lastAccuracy = chartPoints[chartPoints.length - 1]?.accuracy ?? 0
        store.applyLiveSnapshot({
          chartPoints,
          monitorPoints,
          currentRound: rounds.length,
          global: { ...store.global, accuracy: lastAccuracy },
        })

        if (wasHealthy !== true) {
          store.log('server', `실서버 연동 활성 — ${API_BASE} (사일로 ${usage.length}곳 수신)`)
          wasHealthy = true
        }
      } catch (error: unknown) {
        if (wasHealthy !== false) {
          const detail = error instanceof Error ? error.message : String(error)
          store.log('error', `실서버 폴링 실패 — ${detail}. ${LIVE_POLL_INTERVAL_MS / 1000}초 후 재시도.`)
          wasHealthy = false
        }
      }
    }

    void poll()
    const timer = window.setInterval(() => void poll(), LIVE_POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [isLive])
}
