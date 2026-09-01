/**
 * app/ FastAPI 클라이언트.
 * 조회(P0 폴링) 계약: docs/specs/2026-08-21-p0-api-contract.md
 * 변이(P1 — 배포·롤백)는 POST 후 다음 폴링 주기에 상태가 반영된다.
 */

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

export async function apiGet<T>(path: string): Promise<T> {
  if (!API_BASE) throw new Error('VITE_API_BASE가 설정되지 않았습니다')

  const res = await fetch(`${API_BASE}${path}`, {
    headers: buildHeaders(false),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  })
  if (!res.ok) throw new Error(`GET ${path} → HTTP ${res.status}`)
  return (await res.json()) as T
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  if (!API_BASE) throw new Error('VITE_API_BASE가 설정되지 않았습니다')

  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: buildHeaders(body !== undefined),
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  })
  if (!res.ok) {
    // FastAPI 오류 본문의 detail을 살려 사용자에게 원인을 보여준다
    const detail = await res.text().catch(() => '')
    throw new Error(`POST ${path} → HTTP ${res.status}${detail ? ` — ${detail}` : ''}`)
  }
  return (await res.json()) as T
}

// --- 서버 응답 타입 (계약 문서의 필드만 선언) ---------------------------------

export interface ResourceUsageSummary {
  silo_id: string
  last_sample_at: string
  cpu_pct: number
  mem_pct: number
  gpu_pct: number | null
  disk_pct: number | null
  over_budget: boolean
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
}

// --- 모델 레지스트리 · 배포 (P1 — models 탭 배선) ----------------------------

export interface ModelEntryApi {
  name: string
  version: string
  framework: 'pytorch' | 'onnx' | 'tensorflow'
  weights_path: string
  metadata: Record<string, unknown>
  created_at: string
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
}

export interface DeploymentRequestApi {
  model_name: string
  version: string
  strategy: 'realtime' | 'batch' | 'edge'
  target_node_ids: string[]
}

// --- 정제 잡 (P3 — data 탭 배선) -------------------------------------------

export type CleaningShardStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface CleaningShardApi {
  shard_index: number
  silo_id: string
  status: CleaningShardStatus
  rows_in: number
  rows_out: number
  step_counters: Record<string, number>
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
}
