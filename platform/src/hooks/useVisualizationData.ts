import { useEffect, useState } from 'react'
import {
  apiGet,
  isLiveConfigured,
  type BaselineEntryApi,
  type ChartEnvelope,
  type HistogramPayload,
  type ParticipationPayload,
  type SiloBarPayload,
  type TimeSeriesPayload,
  type TopologyPayload,
  type TrainingRoundSummary,
} from '@/api/client'
import { baselineKey } from '@/api/mappers'
import { useSimulationStore } from '@/store/useSimulationStore'

const VIZ_POLL_INTERVAL_MS = 10000

export type TrendMetric = 'accuracy' | 'latency_ms' | 'throughput_rps'
export type ResourceMetric = 'cpu_pct' | 'mem_pct' | 'gpu_pct' | 'disk_pct'

export interface VizQuery {
  /** 성능 추이 대상 모델. null이면 추이를 조회하지 않는다 */
  modelName: string | null
  modelVersion: string | null
  trendMetric: TrendMetric
  resourceMetric: ResourceMetric
  /** 선택한 기준 분포 (`baselineKey`). 목록에 없으면 첫 항목을 쓴다 */
  baselineKey: string | null
}

export interface VizData {
  trend: TimeSeriesPayload | null
  participation: ParticipationPayload
  /** 최근 완료 라운드의 사일로별 표본수. 완료 라운드가 없으면 null */
  roundBar: { roundId: string; payload: SiloBarPayload } | null
  resourceBar: SiloBarPayload
  topology: TopologyPayload
  baselines: BaselineEntryApi[]
  /** 실제로 그린 기준 분포. 기준 분포가 없으면 null */
  histogram: { key: string; payload: HistogramPayload } | null
}

export type VizChartKey = keyof Omit<VizData, 'baselines'>

/** 차트별 결과. 실패한 차트는 `failed`에 담기고 값은 undefined다 */
export interface VizSnapshot {
  data: Partial<VizData>
  failed: VizChartKey[]
}

const getPayload = <P>(path: string): Promise<P> =>
  apiGet<ChartEnvelope<P>>(path).then((envelope) => envelope.payload)

async function fetchRoundBar(): Promise<VizData['roundBar']> {
  // 서버가 최신순으로 준다 — 첫 완료 라운드가 가장 최근
  const rounds = await apiGet<TrainingRoundSummary[]>('/api/training-rounds?status=completed')
  const latest = rounds[0]
  if (!latest) return null
  const payload = await getPayload<SiloBarPayload>(
    `/api/visualizations/silo-bar/round?round_id=${encodeURIComponent(latest.round_id)}`,
  )
  return { roundId: latest.round_id, payload }
}

async function fetchBaselines(
  selected: string | null,
): Promise<Pick<VizData, 'baselines' | 'histogram'>> {
  const baselines = await apiGet<BaselineEntryApi[]>('/api/monitoring/baselines')
  const target = baselines.find((b) => baselineKey(b) === selected) ?? baselines[0]
  if (!target) return { baselines, histogram: null }
  const params = new URLSearchParams({
    model_name: target.model_name,
    version: target.version,
    feature: target.feature,
  })
  const payload = await getPayload<HistogramPayload>(`/api/visualizations/histogram?${params}`)
  return { baselines, histogram: { key: baselineKey(target), payload } }
}

/** 실패를 undefined로 바꿔 한 차트의 오류가 다른 차트를 막지 않게 한다 */
const settle = <T>(p: Promise<T>): Promise<T | undefined> => p.catch(() => undefined)

async function fetchSnapshot(q: VizQuery): Promise<VizSnapshot> {
  const trendParams =
    q.modelName && q.modelVersion
      ? new URLSearchParams({ model_name: q.modelName, version: q.modelVersion, metric: q.trendMetric })
      : null
  const [trend, participation, roundBar, resourceBar, topology, baselines] = await Promise.all([
    trendParams
      ? settle(getPayload<TimeSeriesPayload>(`/api/visualizations/timeseries?${trendParams}`))
      : Promise.resolve(null),
    settle(getPayload<ParticipationPayload>('/api/visualizations/heatmap/participation')),
    settle(fetchRoundBar()),
    settle(getPayload<SiloBarPayload>(`/api/visualizations/silo-bar/resource?metric=${q.resourceMetric}`)),
    settle(getPayload<TopologyPayload>('/api/visualizations/topology')),
    settle(fetchBaselines(q.baselineKey)),
  ])
  const data: Partial<VizData> = {
    trend,
    participation,
    roundBar,
    resourceBar,
    topology,
    baselines: baselines?.baselines,
    histogram: baselines?.histogram,
  }
  const failed = (Object.keys(data) as Array<keyof VizData>).filter(
    (key): key is VizChartKey => key !== 'baselines' && data[key] === undefined,
  )
  return { data, failed }
}

/**
 * 시각화 탭 전용 조회. 탭이 열려 있고 라이브 모드일 때만 10초 주기로 돈다.
 * 전역 5초 폴링(useLivePolling)과 분리 — 다른 탭에는 부하를 주지 않는다.
 * 선택(모델·지표·기준 분포)이 바뀌면 진행 중 요청을 버리고 즉시 다시 조회한다.
 */
export function useVisualizationData(query: VizQuery): { isLive: boolean; snapshot: VizSnapshot | null } {
  const mockEnabled = useSimulationStore((s) => s.mockEnabled)
  const activeTab = useSimulationStore((s) => s.activeTab)
  const isLive = !mockEnabled && isLiveConfigured() && activeTab === 'visualization'
  // ponytail: 이 탭만 쓰는 조회 결과라 store 대신 훅 상태 — 다른 화면이 쓰게 되면 store로 옮긴다
  const [snapshot, setSnapshot] = useState<VizSnapshot | null>(null)

  const { modelName, modelVersion, trendMetric, resourceMetric } = query
  const selectedBaseline = query.baselineKey

  useEffect(() => {
    if (!isLive) return

    // 선택 변경·언마운트 후 도착한 응답이 화면을 덮어쓰지 않도록 무효화한다
    let cancelled = false
    let inFlight = false
    const q: VizQuery = {
      modelName,
      modelVersion,
      trendMetric,
      resourceMetric,
      baselineKey: selectedBaseline,
    }

    const poll = async () => {
      if (inFlight) return // 이전 주기 요청이 아직 진행 중 — 겹침 방지
      inFlight = true
      try {
        const next = await fetchSnapshot(q)
        if (!cancelled) setSnapshot(next)
      } finally {
        inFlight = false
      }
    }

    void poll()
    const timer = window.setInterval(() => void poll(), VIZ_POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [isLive, modelName, modelVersion, trendMetric, resourceMetric, selectedBaseline])

  return { isLive, snapshot }
}
