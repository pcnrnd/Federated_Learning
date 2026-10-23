/**
 * app/ FastAPI 클라이언트.
 * 조회(P0 폴링) 계약: docs/specs/2026-08-21-p0-api-contract.md
 * 변이(P1 — 배포·롤백)는 POST 후 다음 폴링 주기에 상태가 반영된다.
 */

import { useSimulationStore } from '@/store/useSimulationStore'

const REQUEST_TIMEOUT_MS = 4000

export const API_BASE: string | undefined = import.meta.env.VITE_API_BASE
const API_KEY: string | undefined = import.meta.env.VITE_FED_API_KEY

/** 실서버 연동이 구성돼 있는가 (목 OFF와 조합해 라이브 모드 여부 결정) */
export function isLiveConfigured(): boolean {
  return typeof API_BASE === 'string' && API_BASE.length > 0
}

function buildHeaders(hasBody: boolean): Record<string, string> {
  const headers: Record<string, string> = {}
  if (hasBody) headers['Content-Type'] = 'application/json'
  if (API_KEY) headers['X-FED-API-Key'] = API_KEY
  return headers
}

/** 화면에 쓰는 상태별 안내. HTTP 코드·경로·응답 원문은 화면에 올리지 않는다. */
function statusMessage(status: number): string {
  if (status === 400 || status === 422) return '입력값을 확인한 뒤 다시 시도하세요'
  if (status === 401 || status === 403) return '권한이 없어 요청을 처리할 수 없습니다'
  if (status === 404) return '요청한 대상을 찾을 수 없습니다'
  if (status === 409) return '현재 상태에서는 요청을 처리할 수 없습니다'
  return '서버 처리 중 문제가 발생했습니다. 잠시 후 다시 시도하세요'
}

/** 서버가 준 한국어 설명을 화면 문구로 바꿔 쓰는 표. 경로 접두어별로 의미가 다른 문구만 둔다. */
const DETAIL_REWRITES: ReadonlyArray<[pathPrefix: string, detail: string, message: string]> = [
  ['/api/packaging', '실제 가중치 파일이 없거나 비어 있습니다', '모델 가중치 파일이 없어 패키징할 수 없습니다'],
]

const isReadable = (text: string): boolean => /[가-힣]/.test(text) && !/[{}[\]<>]|\/api\/|https?:|HTTP/.test(text)

/** Pydantic 검증 오류 목록에서 한국어 msg만 고른다. loc·input(입력한 env 값 포함)은 쓰지 않는다. */
function validationMessages(items: unknown[]): string | null {
  const messages = items
    .map((item) => (item as { msg?: unknown })?.msg)
    .filter((msg): msg is string => typeof msg === 'string')
    .map((msg) => msg.replace(/^Value error,\s*/, ''))
    .filter(isReadable)
  return messages.length ? [...new Set(messages)].join(' · ') : null
}

/**
 * 오류 응답을 사용자 문구로 바꾼다. 서버 detail이 한국어 설명 문장이면 그대로 쓰고,
 * JSON·경로·영문 검증 메시지는 상태별 안내로 대신한다.
 */
export function apiErrorMessage(path: string, status: number, body: string): string {
  let detail: unknown
  try {
    detail = (JSON.parse(body) as { detail?: unknown } | null)?.detail
  } catch {
    detail = undefined
  }
  if (Array.isArray(detail)) return validationMessages(detail) ?? statusMessage(status)
  if (typeof detail !== 'string') return statusMessage(status)
  const rewrite = DETAIL_REWRITES.find(([prefix, text]) => path.startsWith(prefix) && detail === text)
  if (rewrite) return rewrite[2]
  return isReadable(detail) ? detail : statusMessage(status)
}

// Pydantic input/context에는 입력한 env 값이 포함될 수 있으므로 배포 계열 응답 본문은 콘솔에도 남기지 않는다.
const BODY_REDACTED_PREFIXES = ['/api/deployments', '/api/serving-routes', '/api/shadow-deployments']

async function failedResponse(method: string, path: string, res: Response): Promise<Error> {
  const body = await res.text().catch(() => '')
  const logged = BODY_REDACTED_PREFIXES.some((prefix) => path.startsWith(prefix)) ? '(본문 생략)' : body
  console.error(`[api] ${method} ${path} → HTTP ${res.status}`, logged)
  return new Error(apiErrorMessage(path, res.status, body))
}

async function request(method: string, path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`${API_BASE}${path}`, {
      ...init, ...(method === 'GET' ? {} : { method }), signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) })
  } catch (error) {
    console.error(`[api] ${method} ${path} 요청 실패`, error)
    throw new Error('서버에 연결할 수 없습니다. 연결 상태를 확인하세요')
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  if (!API_BASE) throw new Error('VITE_API_BASE가 설정되지 않았습니다')

  const res = await request('GET', path, { headers: buildHeaders(false) })
  if (!res.ok) throw await failedResponse('GET', path, res)
  return (await res.json()) as T
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return apiMutation<T>('POST', path, body)
}

export interface RidgePredictionApi {
  model: string
  version: string
  artifact_id: string
  weights_checksum: string
  result_id: string
  predictions: number[]
}

/** 모델 이름은 URL segment로 변환하지 않고 JSON의 정확한 정체성을 유지한다. */
export function predictRegisteredRidge(name: string, version: string, inputs: unknown[]): Promise<RidgePredictionApi> {
  return apiPost<RidgePredictionApi>('/api/models/predict', { name, version, inputs })
}

export async function apiMutation<T>(method: 'POST' | 'PUT' | 'DELETE', path: string, body?: unknown): Promise<T> {
  // 숨겨진 폼/오래된 이벤트도 데모 모드에서는 실서버에 쓸 수 없다.
  if (useSimulationStore.getState().mockEnabled) throw new Error('예시 데이터 표시 중에는 서버를 변경하지 않습니다')
  if (!API_BASE) throw new Error('VITE_API_BASE가 설정되지 않았습니다')

  const res = await request(method, path, {
    headers: buildHeaders(body !== undefined),
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  if (!res.ok) throw await failedResponse(method, path, res)
  return (await res.json()) as T
}

// --- 서버 응답 타입 (계약 문서의 필드만 선언) ---------------------------------

export interface ResourceUsageSummary {
  silo_id: string
  last_sample_at: string
  cpu_pct: number | null
  mem_pct: number | null
  gpu_pct: number | null
  disk_pct: number | null
  over_budget: boolean
  availability?: 'unknown' | 'unmonitored' | 'available' | 'over_budget'
  measurement_scope?: Record<string, string>
  unavailable?: Record<string, string>
  cpu_cores?: number | null
  mem_used_bytes?: number | null
  mem_limit_bytes?: number | null
  capabilities?: Record<string, boolean>
}

export interface SiloRegistrationApi {
  silo_id: string
  label: string
  base_url: string
  collect_interval_seconds: number
}

export interface SiloGroupApi {
  group_id: string
  description: string
  member_node_ids: string[]
  aggregator_node_id: string | null
  tags?: string[]
  metadata?: Record<string, unknown>
}

export interface ResourceSampleApi {
  silo_id: string
  timestamp: string
  cpu_pct: number | null
  mem_pct: number | null
  disk_pct: number | null
  measurement_scope?: Record<string, string>
  unavailable?: Record<string, string>
  cpu_cores?: number | null
  mem_used_bytes?: number | null
}

export interface ResourceLimit {
  silo_id: string
  cpu_pct_max: number | null
  mem_pct_max: number | null
  gpu_pct_max: number | null
  disk_pct_max: number | null
}

export interface MetricSample {
  node_id: string
  model_name: string
  version: string
  metric: string
  value: number
  timestamp: string
}

export interface Paginated<T> {
  items: T[]
  total: number
}

export interface TrainingRoundSummary {
  round_id: string
  status: 'open' | 'aggregating' | 'completed' | 'failed'
  contributors: string[]
  total_samples: number
  model_name?: string
  version?: string
  parent_round_id?: string | null
  base_checksum?: string | null
  space_checksum?: string | null
  result?: RidgeResultApi | null
  error?: string | null
}

export interface RidgeResultApi {
  result_id: string
  checksum: string
  parameters: number[]
  parameter_dim: number
  total_samples: number
  format: string
  features: string[] | null
  target: string | null
}

export interface TrainingJobApi {
  job_id: string
  model_name: string
  version: string
  status: 'active' | 'paused' | 'completed' | 'cancelled' | 'failed'
  rounds_completed: number
  max_rounds: number
  current_round_id: string | null
  last_completed_round_id?: string | null
  error?: string | null
}

// --- 모델 레지스트리 · 배포 (P1 — models 탭 배선) ----------------------------

export interface ModelEntryApi {
  name: string
  version: string
  framework: 'pytorch' | 'onnx' | 'tensorflow' | 'ridge'
  weights_path: string
  metadata: Record<string, unknown>
  created_at: string
  status?: 'active' | 'archived'
  package?: PackageRecordApi | null
}

export interface PackageRecordApi {
  model_name: string
  version: string
  status: 'unbuilt' | 'building' | 'built' | 'failed' | 'unknown'
  package_id?: string | null
  image_tag?: string | null
  image_digest?: string | null
  base_image?: string | null
  artifact_id?: string | null
  weights_checksum?: string | null
  manifest_checksum?: string | null
  requested_at?: string | null
  built_at?: string | null
  error?: string | null
}

export type DeploymentStatusApi = 'pending' | 'running' | 'failed' | 'rolled_back' | 'stopped'

export interface DeploymentEntryApi {
  deployment_id: string
  model_name: string
  version: string
  image_tag: string
  strategy: 'realtime' | 'batch' | 'edge'
  target_node_ids: string[]
  status: DeploymentStatusApi
  created_at: string
  previous_deployment_id: string | null
  error: string | null
  configuration?: DeploymentRequestApi | null
  expected_image_id?: string | null
  verified_at?: string | null
  target_results?: Record<string, { status: 'pending' | 'launching' | 'running' | 'failed';
    endpoint?: string | null; image_id?: string | null; weights_checksum?: string | null; error_code?: string | null }>
  is_schedule?: boolean
  schedule_active?: boolean
  interval_seconds?: number | null
  next_due_at?: string | null
  occurrence?: number
  schedule_parent_id?: string | null
  cleanup_pending?: boolean
}

export interface DeploymentRequestApi {
  model_name: string
  version: string
  strategy: 'realtime' | 'batch' | 'edge'
  target_node_ids: string[]
  env?: Record<string, string>
  interval_seconds?: number
  request_id?: string
  inference_port?: number
  probe_inputs?: unknown[]
}

// --- 정제 잡 (P3 — data 탭 배선) -------------------------------------------

export type CleaningShardStatus = 'pending' | 'running' | 'retry_wait' | 'completed' | 'failed'

export interface CleaningShardApi {
  shard_index: number
  silo_id: string
  status: CleaningShardStatus
  rows_in: number
  rows_out: number
  step_counters: Record<string, number>
  processed_units?: number
  total_units?: number
  attempt?: number
  stage?: string
  error?: string | null
  output_hash?: string | null
}

export interface CleaningJobApi {
  job_id: string
  recipe_name: string
  recipe_version: string
  status: 'pending' | 'running' | 'completed' | 'partial' | 'failed'
  shards: CleaningShardApi[]
  total_rows_in: number
  total_rows_out: number
  aggregated_counters: Record<string, number>
  dataset_label: string
  updated_at: string
  scheduled_at?: string | null
  interval_seconds?: number | null
  depends_on?: string[]
  occurrence?: number
  generation?: number
  partitions?: number
  events?: Array<{ event_id: string; message: string; at: string; kind: string }>
}

// --- 시각화 5종 (/api/visualizations · 기준 분포 목록) -------------------------
// 응답 형식 정본: review-system queues/federated-viz-5-screens-plan-20261006.md §응답 형식

export type ChartType = 'timeseries' | 'histogram' | 'silo_bar' | 'heatmap' | 'topology'

export interface ChartEnvelope<P> {
  chart_type: ChartType
  title: string
  x_axis: string
  y_axis: string
  payload: P
}

export interface TimeSeriesPayload {
  /** silo_id → 시간순 포인트 */
  series: Record<string, Array<{ timestamp: string; value: number }>>
}

export interface HistogramPayload {
  bin_edges: number[]
  bin_counts: number[]
}

export interface SiloBarPayload {
  items: Array<{ silo_id: string; value: number }>
}

export type ParticipationStatus =
  | 'contributed'
  | 'via_aggregator'
  | 'missing'
  | 'pending'
  | 'not_member'

export interface ParticipationRoundMeta {
  round_id: string
  status: TrainingRoundSummary['status']
  created_at: string
  group_id: string
}

export interface ParticipationPayload {
  row_labels: string[]
  col_labels: string[]
  col_meta: ParticipationRoundMeta[]
  /** contributed 칸만 표본수, 나머지는 null */
  matrix: Array<Array<number | null>>
  cell_status: ParticipationStatus[][]
}

export type TopologyRole = 'central' | 'client' | 'aggregator' | 'group' | 'deployment'

export interface TopologyNodeApi {
  id: string
  label: string
  role: TopologyRole
  group: string | null
  over_budget: boolean | null
}

export interface TopologyEdgeApi {
  source: string
  target: string
  kind: 'group' | 'deployment' | 'aggregation'
  metadata: Record<string, unknown>
}

export interface TopologyPayload {
  nodes: TopologyNodeApi[]
  edges: TopologyEdgeApi[]
}

export interface BaselineEntryApi {
  model_name: string
  version: string
  feature: string
  bin_count: number
}
