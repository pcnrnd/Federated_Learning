import { create } from 'zustand'
import { JOB_STEP_MS, SILO_SEEDS } from '@/constants/simulation'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { CleaningShardStatus } from '@/api/client'
import { apiGet, apiPost, type CleaningJobApi } from '@/api/client'
import { mapCleaningJobs } from '@/api/mappers'
import { dataSourceGuard } from '@/lib/dataSource'
import type { CleaningJobSummary, Job, LogKind } from '@/types/simulation'

function logToConsole(kind: LogKind, message: string): void {
  useSimulationStore.getState().log(kind, message)
}

/** 사일로별 데이터 파이프라인 상태 (사일로 식별자는 useSiloStore가 단일 소스) */
export interface SiloDataFields {
  cleansePct: number
  shardCount: number
  records: number
  /** 실서버 정제 샤드 상태. undefined면 목 시드 데이터 */
  cleanseStatus?: CleaningShardStatus
  /** 실서버 step별 정제 카운터 (해당 사일로 샤드분) */
  stepCounters?: Record<string, number>
}

// 사일로별 정제율/샤드/레코드 시드 (SILO_SEEDS id 순서 대응, 결정적 값)
const CLEANSE_SEED = [100, 72, 38, 88, 64, 95]

/** 실서버 정제 레시피와 같은 step 이름 — 데모 카드·잡 표가 실서버와 같은 칩으로 보이게 한다 */
const DEMO_COUNTER_STEPS = [
  'map_schema.rows.entity', 'map_schema.cast_failed', 'union_sources.combined', 'union_sources.duplicates.within',
  'join_sources.matched', 'join_sources.excluded.left_only', 'parse_records.out', 'parse_records.conversion_failed',
  'reconcile.conflicts', 'reconcile.resolved.latest', 'validate_schema.excluded.missing', 'validate_schema.out',
] as const

function demoStepCounters(records: number): Record<string, number> {
  return Object.fromEntries(DEMO_COUNTER_STEPS.map((step, i) => [step, Math.round(records / (8 + i * 11))]))
}

function seedDataBySilo(): Record<number, SiloDataFields> {
  const out: Record<number, SiloDataFields> = {}
  SILO_SEEDS.forEach((silo, i) => {
    const cleansePct = CLEANSE_SEED[i] ?? 50
    const records = 120_000 + silo.id * 47_300
    out[silo.id] = {
      cleansePct,
      shardCount: ((silo.id * 2) % 6) + 3,
      records,
      cleanseStatus: cleansePct >= 100 ? 'completed' : 'running',
      stepCounters: demoStepCounters(records),
    }
  })
  return out
}

/** 정제 잡 현황 표의 데모 행 — 서버 잡 목록(liveCleaningJobs)과 섞지 않는다 */
export const DEMO_CLEANING_JOBS: CleaningJobSummary[] = ([
  { jobId: 'clean-daily-0601', status: 'completed', totalRowsIn: 1_412_400, totalRowsOut: 1_355_900 },
  { jobId: 'clean-daily-0602', status: 'running', totalRowsIn: 1_398_700, totalRowsOut: 702_300 },
] as const).map((job) => ({ ...job, recipe: 'silo-standard@1.0.0', datasetLabel: 'silo-sources',
  counters: demoStepCounters(job.totalRowsIn), updatedAt: '2026-06-02T09:00:00Z' }))

function seedJobs(): Job[] {
  return [
    { id: 'job-ingest', name: '원본 수집 (Ingest)', schedule: '*/10 * * * *', dependsOn: [], state: 'done' },
    { id: 'job-cleanse', name: '데이터 정제 (Cleanse)', schedule: '0 * * * *', dependsOn: ['job-ingest'], state: 'queued' },
    { id: 'job-shard', name: '샤딩 분할 (Shard)', schedule: '0 */2 * * *', dependsOn: ['job-cleanse'], state: 'queued' },
    { id: 'job-validate', name: '품질 검증 (Validate)', schedule: '0 */2 * * *', dependsOn: ['job-cleanse'], state: 'queued' },
    { id: 'job-export', name: '학습셋 반출 (Export)', schedule: '0 6 * * *', dependsOn: ['job-shard', 'job-validate'], state: 'queued' },
  ]
}

export interface NewJobInput {
  name: string
  schedule: string
  dependsOn: string[]
  targetSiloId?: number
}

export interface DataStore {
  dataBySilo: Record<number, SiloDataFields>
  jobs: Job[]
  /** 실서버 정제 잡 현황 (라이브 폴링이 채운다 — 목 모드에서는 항상 빈 배열) */
  liveCleaningJobs: CleaningJobSummary[]
  liveDraft: Record<string, string>
  patchLiveDraft: (patch: Record<string, string>) => void
  livePending: boolean
  liveError: string | null
  deliveredEvents: string[]
  mutationEpoch: number
  createLiveJob: () => Promise<boolean>
  rescheduleLiveJob: (jobId: string, at: string) => Promise<boolean>
  refreshLiveCleaning: () => Promise<void>

  // 사일로 등록/해제 전파 (useSiloStore가 호출)
  ensureSiloData: (siloId: number) => void
  removeSiloData: (siloId: number) => void

  /** 라이브 모드 — /api/cleaning-jobs 폴링 결과를 반영한다 */
  applyLiveCleaning: (
    dataBySilo: Record<number, SiloDataFields>,
    jobs: CleaningJobSummary[],
  ) => void

  // 6.5 스케줄러 제어
  canRun: (id: string) => boolean
  runJob: (id: string) => void
  pauseJob: (id: string) => void

  // 파이프라인(작업) 등록/해제
  addJob: (input: NewJobInput) => void
  removeJob: (id: string) => void

  /** 목 off — 정제·파이프라인 데이터를 비운다 */
  clearAll: () => void
  /** 목 on — 초기 시드로 복원한다 */
  reseed: () => void
}

let jobSeq = 1
const nextJobId = (): string => `job-u${jobSeq++}`

function depsSatisfied(jobs: Job[], job: Job): boolean {
  return job.dependsOn.every((depId) => jobs.find((j) => j.id === depId)?.state === 'done')
}

function initialLiveDraft(): Record<string, string> {
  return { job_id: '', recipe_name: '', recipe_version: '1.0.0', group_id: '',
    dataset_label: 'silo-sources', scheduled_at: '', interval_seconds: '', max_occurrences: '',
    depends_on: '', max_attempts: '3', retry_backoff_seconds: '5', timeout_seconds: '300', partitions: '4', parallelism: '2' }
}

export const useDataStore = create<DataStore>((set, get) => ({
  dataBySilo: useSimulationStore.getState().mockEnabled ? seedDataBySilo() : {},
  jobs: useSimulationStore.getState().mockEnabled ? seedJobs() : [],
  liveCleaningJobs: [],
  liveDraft: initialLiveDraft(),
  patchLiveDraft: (patch) => set((s) => ({ liveDraft: { ...s.liveDraft, ...patch } })),
  livePending: false, liveError: null, deliveredEvents: [], mutationEpoch: 0,
  refreshLiveCleaning: async () => {
    const current = dataSourceGuard(false)
    if (!current()) return
    const mapped = mapCleaningJobs(await apiGet<CleaningJobApi[]>('/api/cleaning-jobs'))
    if (current()) get().applyLiveCleaning(mapped.dataBySilo, mapped.jobs)
  },
  createLiveJob: async () => {
    const current = dataSourceGuard(false)
    if (!current()) return false
    if (get().livePending) return false
    set((s) => ({ livePending: true, liveError: null, mutationEpoch: s.mutationEpoch + 1 }))
    try {
      const d = get().liveDraft
      const saved = Object.fromEntries(Object.entries(d).filter(([key]) => !key.startsWith('reschedule:')))
      const body = { ...saved, scheduled_at: d.scheduled_at ? new Date(d.scheduled_at).toISOString() : null,
        depends_on: d.depends_on.split(',').map((s) => s.trim()).filter(Boolean),
        interval_seconds: d.interval_seconds ? Number(d.interval_seconds) : null,
        max_occurrences: d.max_occurrences ? Number(d.max_occurrences) : null,
        max_attempts: Number(d.max_attempts), retry_backoff_seconds: Number(d.retry_backoff_seconds),
        timeout_seconds: Number(d.timeout_seconds), partitions: Number(d.partitions), parallelism: Number(d.parallelism) }
      await apiPost('/api/cleaning-jobs', body)
      if (!current()) return false
      await get().refreshLiveCleaning()
      return true
    } catch (error) { if (current()) set({ liveError: error instanceof Error ? error.message : String(error) }); return false }
    finally { if (current()) set({ livePending: false }) }
  },
  rescheduleLiveJob: async (jobId, at) => {
    const current = dataSourceGuard(false)
    if (!current()) return false
    if (get().livePending) return false
    set((s) => ({ livePending: true, liveError: null, mutationEpoch: s.mutationEpoch + 1 }))
    try {
      await apiPost(`/api/cleaning-jobs/${encodeURIComponent(jobId)}/reschedule`, { scheduled_at: new Date(at).toISOString() })
      if (!current()) return false
      await get().refreshLiveCleaning()
      return true
    } catch (error) { if (current()) set({ liveError: error instanceof Error ? error.message : String(error) }); return false }
    finally { if (current()) set({ livePending: false }) }
  },

  clearAll: () => set((s) => ({ dataBySilo: {}, jobs: [], liveCleaningJobs: [], liveDraft: initialLiveDraft(), livePending: false, liveError: null, deliveredEvents: [], mutationEpoch: s.mutationEpoch + 1 })),
  reseed: () =>
    set((s) => ({ dataBySilo: seedDataBySilo(), jobs: seedJobs(), liveCleaningJobs: [], liveDraft: initialLiveDraft(), livePending: false, liveError: null, deliveredEvents: [], mutationEpoch: s.mutationEpoch + 1 })),

  applyLiveCleaning: (dataBySilo, liveCleaningJobs) => {
    if (useSimulationStore.getState().mockEnabled) return
    const delivered = new Set(get().deliveredEvents)
    for (const job of liveCleaningJobs) for (const event of job.events ?? []) {
      if (delivered.has(event.event_id)) continue
      delivered.add(event.event_id)
      logToConsole('error', `[정제 ${job.jobId}] ${event.message} (${event.at})`)
    }
    set({ dataBySilo, liveCleaningJobs, deliveredEvents: [...delivered] })
  },

  ensureSiloData: (siloId) => {
    if (get().dataBySilo[siloId]) return
    set((state) => ({
      dataBySilo: { ...state.dataBySilo, [siloId]: { cleansePct: 0, shardCount: 1, records: 0 } },
    }))
  },

  removeSiloData: (siloId) =>
    set((state) => {
      const { [siloId]: _removed, ...rest } = state.dataBySilo
      return { dataBySilo: rest }
    }),

  canRun: (id) => {
    if (!useSimulationStore.getState().mockEnabled) return false
    const jobs = get().jobs
    const job = jobs.find((j) => j.id === id)
    if (!job) return false
    return (job.state === 'queued' || job.state === 'failed') && depsSatisfied(jobs, job)
  },

  runJob: (id) => {
    const current = dataSourceGuard(true)
    if (!current()) return
    const job = get().jobs.find((j) => j.id === id)
    if (!job) return

    if (!depsSatisfied(get().jobs, job)) {
      logToConsole('system', `[${job.name}] 선행 작업 미완료로 대기 상태를 유지합니다.`)
      return
    }

    set((state) => ({
      jobs: state.jobs.map((j) => (j.id === id ? { ...j, state: 'running' } : j)),
    }))
    logToConsole('server', `[${job.name}] 작업을 실행합니다. (스케줄: ${job.schedule})`)

    window.setTimeout(() => {
      if (!current()) return
      const cur = get().jobs.find((j) => j.id === id)
      if (!cur || cur.state !== 'running') return
      set((state) => ({
        jobs: state.jobs.map((j) => (j.id === id ? { ...j, state: 'done' } : j)),
      }))
      logToConsole('success', `[${job.name}] 작업이 완료되었습니다.`)

      // 작업 완료가 정제율/샤드에 인과적으로 반영되도록 연동
      if (id === 'job-cleanse') {
        set((state) => {
          const updated: Record<number, SiloDataFields> = {}
          for (const [k, v] of Object.entries(state.dataBySilo)) {
            updated[Number(k)] = v.cleansePct < 100 ? { ...v, cleansePct: 100 } : v
          }
          return { dataBySilo: updated }
        })
        logToConsole('system', '[데이터 정제] 전 사일로 정제율을 100%로 갱신했습니다.')
      }
    }, JOB_STEP_MS)
  },

  pauseJob: (id) => {
    if (!useSimulationStore.getState().mockEnabled) return
    const job = get().jobs.find((j) => j.id === id)
    if (!job || job.state !== 'running') return
    set((state) => ({
      jobs: state.jobs.map((j) => (j.id === id ? { ...j, state: 'queued' } : j)),
    }))
    logToConsole('system', `[${job.name}] 작업을 일시중지하여 대기열로 되돌렸습니다.`)
  },

  addJob: (input) => {
    if (!useSimulationStore.getState().mockEnabled) return
    const job: Job = {
      id: nextJobId(),
      name: input.name.trim(),
      schedule: input.schedule.trim(),
      dependsOn: input.dependsOn,
      state: 'queued',
      ...(input.targetSiloId !== undefined ? { targetSiloId: input.targetSiloId } : {}),
    }
    set((state) => ({ jobs: [...state.jobs, job] }))
    logToConsole('server', `[${job.name}] 파이프라인 작업을 등록했습니다. (스케줄: ${job.schedule})`)
  },

  removeJob: (id) => {
    if (!useSimulationStore.getState().mockEnabled) return
    const target = get().jobs.find((j) => j.id === id)
    if (!target) return
    set((state) => ({
      // 삭제 대상에 의존하던 작업의 의존성에서도 제거
      jobs: state.jobs
        .filter((j) => j.id !== id)
        .map((j) =>
          j.dependsOn.includes(id)
            ? { ...j, dependsOn: j.dependsOn.filter((d) => d !== id) }
            : j,
        ),
    }))
    logToConsole('error', `[${target.name}] 파이프라인 작업을 삭제했습니다.`)
  },
}))

useSimulationStore.subscribe((state, previous) => {
  if (state.mockEnabled !== previous.mockEnabled) {
    if (state.mockEnabled) useDataStore.getState().reseed()
    else useDataStore.getState().clearAll()
  }
})
