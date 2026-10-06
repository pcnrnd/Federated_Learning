import type {
  BaselineEntryApi,
  CleaningJobApi,
  DeploymentEntryApi,
  DeploymentStatusApi,
  HistogramPayload,
  MetricSample,
  ModelEntryApi,
  ParticipationPayload,
  ParticipationStatus,
  ResourceLimit,
  ResourceUsageSummary,
  SiloBarPayload,
  TimeSeriesPayload,
  TrainingRoundSummary,
} from '@/api/client'
import type { SiloDataFields } from '@/store/useDataStore'
import type {
  Algorithm,
  ChartPoint,
  CleaningJobSummary,
  Deployment,
  DeployState,
  ModelVersion,
  MonitorPoint,
  Silo,
} from '@/types/simulation'

/**
 * 서버 응답 → UI 스토어 형태 변환 (순수 함수).
 * 계약: docs/specs/2026-08-21-p0-api-contract.md
 */

const DEFAULT_THRESHOLDS = { cpu: 85, mem: 80, disk: 90 } as const

/** "silo-3" → 3. 끝자리 숫자가 없으면 목록 순번+1000으로 충돌을 피한다 */
export function siloIdToNumber(siloId: string, index: number): number {
  const match = /(\d+)\s*$/.exec(siloId)
  return match ? Number(match[1]) : 1000 + index
}

export function mapUsageToSilos(
  usage: readonly ResourceUsageSummary[],
  limits: readonly ResourceLimit[],
): Silo[] {
  const limitBySilo = new Map(limits.map((l) => [l.silo_id, l]))
  return usage.map((u, i) => {
    const limit = limitBySilo.get(u.silo_id)
    return {
      id: siloIdToNumber(u.silo_id, i),
      name: u.silo_id,
      endpoint: '(실서버)',
      collectIntervalSec: 0,
      cpu: Math.round(u.cpu_pct),
      mem: Math.round(u.mem_pct),
      disk: Math.round(u.disk_pct ?? 0),
      thresholds: {
        cpu: limit?.cpu_pct_max ?? DEFAULT_THRESHOLDS.cpu,
        mem: limit?.mem_pct_max ?? DEFAULT_THRESHOLDS.mem,
        disk: limit?.disk_pct_max ?? DEFAULT_THRESHOLDS.disk,
      },
    }
  })
}

// --- 모델 레지스트리 · 배포 (P1) ---------------------------------------------

/** 서버 (name, version) → UI 모델 id. 라운드트립 가능해야 배포 요청에 되쓸 수 있다 */
export function modelKey(name: string, version: string): string {
  return `${name}@${version}`
}

export function parseModelKey(id: string): { name: string; version: string } {
  const at = id.lastIndexOf('@')
  return at < 0
    ? { name: id, version: '' }
    : { name: id.slice(0, at), version: id.slice(at + 1) }
}

const ALGORITHMS: readonly Algorithm[] = ['fedavg', 'fedmedian', 'secagg']

const DEPLOY_STATE_MAP: Record<DeploymentStatusApi, DeployState> = {
  pending: 'pending',
  running: 'done',
  failed: 'failed',
  stopped: 'stopped',
  rolled_back: 'rolled_back',
}

function metaNumber(meta: Record<string, unknown>, key: string): number | undefined {
  const v = meta[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined
}

export function mapModelsToVersions(
  models: readonly ModelEntryApi[],
  deployments: readonly DeploymentEntryApi[],
): ModelVersion[] {
  // 배포 상태는 레지스트리에 없다 — running 배포가 있는 버전을 '배포됨'으로 승격
  const running = new Set(
    deployments
      .filter((d) => d.status === 'running')
      .map((d) => modelKey(d.model_name, d.version)),
  )
  return models.map((m) => {
    const meta = m.metadata ?? {}
    const algorithm = ALGORITHMS.find((a) => a === meta.algorithm) ?? 'fedavg'
    const note = typeof meta.note === 'string' && meta.note ? { note: meta.note } : {}
    return {
      id: modelKey(m.name, m.version),
      project: m.name,
      version: m.version,
      status: running.has(modelKey(m.name, m.version)) ? 'deployed' : 'experimental',
      // 서버 metadata.accuracy는 0~1 스케일 가정 (지표 API와 동일) → UI %
      accuracy: Math.round((metaNumber(meta, 'accuracy') ?? 0) * 10000) / 100,
      algorithm,
      rounds: metaNumber(meta, 'rounds') ?? 0,
      createdAt: m.created_at.slice(0, 10),
      ...note,
    }
  })
}

export function mapApiDeployments(deployments: readonly DeploymentEntryApi[]): Deployment[] {
  let fallbackIndex = 0
  return deployments.map((d) => ({
    id: d.deployment_id,
    modelId: modelKey(d.model_name, d.version),
    modelLabel: `${d.model_name} ${d.version}`,
    strategy: d.strategy,
    targetSiloIds: d.target_node_ids.map((n) => siloIdToNumber(n, fallbackIndex++)),
    state: DEPLOY_STATE_MAP[d.status],
    ts: d.created_at.slice(11, 19),
  }))
}

export interface LiveCleaningMapped {
  dataBySilo: Record<number, SiloDataFields>
  jobs: CleaningJobSummary[]
}

/**
 * 정제 잡 목록 → data 탭 상태.
 * 잡은 최신순으로 온다(서버가 created_at desc 정렬) — 사일로별로 가장 최근 샤드가 이긴다.
 */
export function mapCleaningJobs(jobs: readonly CleaningJobApi[]): LiveCleaningMapped {
  const dataBySilo: Record<number, SiloDataFields> = {}
  let fallbackIndex = 0
  for (const job of jobs) {
    for (const shard of job.shards) {
      const id = siloIdToNumber(shard.silo_id, fallbackIndex++)
      if (dataBySilo[id]) continue // 더 최신 잡의 샤드가 이미 반영됨
      dataBySilo[id] = {
        cleansePct: shard.status === 'completed' ? 100 : 0,
        shardCount: 1, // 현 백엔드는 잡당 사일로 1샤드
        records: shard.rows_in,
        cleanseStatus: shard.status,
        stepCounters: shard.step_counters,
      }
    }
  }
  return {
    dataBySilo,
    jobs: jobs.map((j) => ({
      jobId: j.job_id,
      recipe: `${j.recipe_name}@${j.recipe_version}`,
      status: j.status,
      datasetLabel: j.dataset_label,
      totalRowsIn: j.total_rows_in,
      totalRowsOut: j.total_rows_out,
      counters: j.aggregated_counters,
      updatedAt: j.updated_at,
    })),
  }
}

/** 같은 timestamp의 사일로 값들을 한 라운드로 묶어 평균한다 */
function averageByTimestamp(samples: readonly MetricSample[]): number[] {
  const byTs = new Map<string, number[]>()
  for (const s of samples) {
    const bucket = byTs.get(s.timestamp)
    if (bucket) bucket.push(s.value)
    else byTs.set(s.timestamp, [s.value])
  }
  return [...byTs.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, values]) => values.reduce((sum, v) => sum + v, 0) / values.length)
}

export function mapMetricsToChartPoints(accuracy: readonly MetricSample[]): ChartPoint[] {
  // 서버 accuracy는 0~1 스케일 → UI는 % (부동소수점 잔여 오차 반올림)
  return averageByTimestamp(accuracy).map((v, i) => ({
    round: i,
    accuracy: Math.round(v * 10000) / 100,
    loss: 0, // 서버에 loss 지표 없음 — P2에서 라운드 집계 결과로 대체
  }))
}

export function mapMetricsToMonitorPoints(
  throughput: readonly MetricSample[],
  latency: readonly MetricSample[],
): MonitorPoint[] {
  const rps = averageByTimestamp(throughput)
  const ms = averageByTimestamp(latency)
  const count = Math.max(rps.length, ms.length)
  return Array.from({ length: count }, (_, i) => ({
    round: i,
    throughput: Math.round((rps[i] ?? 0) * 10) / 10,
    latency: Math.round((ms[i] ?? 0) * 10) / 10,
    drift: 0, // 드리프트 조회는 P0 범위 밖
  }))
}

// --- 시각화 5종 (/api/visualizations) ----------------------------------------

/** silo-2가 silo-10보다 앞서도록 숫자 인식 정렬 */
export function compareSiloId(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true })
}

const round2 = (v: number): number => Math.round(v * 100) / 100

export interface SiloSeries {
  siloId: string
  values: Array<number | null>
}

export interface LineChartInput {
  /** 공통 시간축 라벨 (HH:MM:SS) */
  labels: string[]
  series: SiloSeries[]
}

/**
 * 사일로별 시계열 → 공통 시간축 정렬.
 * 사일로가 보내지 않은 시점은 null — 차트가 spanGaps로 이어 그린다.
 * `scale`은 표시 단위 변환용 (accuracy 0~1 → % 는 100).
 */
export function mapTimeseriesToLines(payload: TimeSeriesPayload, scale = 1): LineChartInput {
  const siloIds = Object.keys(payload.series).sort(compareSiloId)
  const timestamps = [
    ...new Set(siloIds.flatMap((id) => payload.series[id].map((p) => p.timestamp))),
  ].sort()
  const column = new Map(timestamps.map((ts, i) => [ts, i]))
  const series = siloIds.map((siloId) => {
    const values: Array<number | null> = timestamps.map(() => null)
    for (const p of payload.series[siloId]) {
      const i = column.get(p.timestamp)
      if (i !== undefined) values[i] = round2(p.value * scale)
    }
    return { siloId, values }
  })
  return { labels: timestamps.map((ts) => ts.slice(11, 19)), series }
}

export interface ParticipationCell {
  status: ParticipationStatus
  /** contributed 칸의 표본수. 그 밖의 상태는 null */
  value: number | null
  /** 0~1 — 격자 안 최대 표본수 대비 비율 (칸 농도) */
  intensity: number
}

export interface ParticipationColumn {
  roundId: string
  label: string
  status: TrainingRoundSummary['status'] | null
  createdAt: string
  /** 직접 제출 + 집계자 경유 */
  participated: number
  /** 그 라운드의 멤버 수 */
  members: number
}

export interface ParticipationGrid {
  columns: ParticipationColumn[]
  rows: Array<{ siloId: string; cells: ParticipationCell[] }>
}

export function mapParticipation(payload: ParticipationPayload): ParticipationGrid {
  const max = payload.matrix
    .flat()
    .reduce<number>((m, v) => (typeof v === 'number' && v > m ? v : m), 0)
  const rows = payload.row_labels.map((siloId, r) => ({
    siloId,
    cells: payload.col_labels.map((_, c): ParticipationCell => {
      const status = payload.cell_status[r]?.[c] ?? 'not_member'
      const value = status === 'contributed' ? (payload.matrix[r]?.[c] ?? null) : null
      return { status, value, intensity: value !== null && max > 0 ? value / max : 0 }
    }),
  }))
  const columns = payload.col_labels.map((label, c): ParticipationColumn => {
    const meta = payload.col_meta[c]
    const statuses = rows.map((row) => row.cells[c].status)
    return {
      roundId: meta?.round_id ?? label,
      label,
      status: meta?.status ?? null,
      createdAt: meta?.created_at ?? '',
      participated: statuses.filter((s) => s === 'contributed' || s === 'via_aggregator').length,
      members: statuses.filter((s) => s !== 'not_member').length,
    }
  })
  return { columns, rows }
}

export interface BarChartInput {
  labels: string[]
  values: number[]
}

export function mapSiloBar(payload: SiloBarPayload): BarChartInput {
  const items = [...payload.items].sort((a, b) => compareSiloId(a.silo_id, b.silo_id))
  return { labels: items.map((i) => i.silo_id), values: items.map((i) => round2(i.value)) }
}

/** 구간 경계 [0, 10, 20] + 개수 [3, 5] → 라벨 ["0–10", "10–20"] */
export function mapHistogram(payload: HistogramPayload): BarChartInput {
  const edge = (i: number): string => {
    const v = payload.bin_edges[i]
    return v === undefined ? '' : String(round2(v))
  }
  return {
    labels: payload.bin_counts.map((_, i) => `${edge(i)}–${edge(i + 1)}`),
    values: [...payload.bin_counts],
  }
}

/** 기준 분포 식별자 — 서버 저장 키(`model::version::feature`)와 같은 모양 */
export function baselineKey(b: BaselineEntryApi): string {
  return `${b.model_name}::${b.version}::${b.feature}`
}
