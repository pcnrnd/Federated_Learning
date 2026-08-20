import { create } from 'zustand'
import { JOB_STEP_MS, SILO_SEEDS } from '@/constants/simulation'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { Job, LogKind } from '@/types/simulation'

function logToConsole(kind: LogKind, message: string): void {
  useSimulationStore.getState().log(kind, message)
}

/** 사일로별 데이터 파이프라인 상태 (사일로 식별자는 useSiloStore가 단일 소스) */
export interface SiloDataFields {
  cleansePct: number
  shardCount: number
  records: number
}

const CLEANSE_STEP_MS = 450
const CLEANSE_STEP_PCT = 22

// 12개 사일로별 정제율/샤드/레코드 시드 (id 순서 대응, 결정적 값)
const CLEANSE_SEED = [100, 72, 38, 88, 64, 95, 41, 79, 56, 100, 33, 68]

function seedDataBySilo(): Record<number, SiloDataFields> {
  const out: Record<number, SiloDataFields> = {}
  SILO_SEEDS.forEach((silo, i) => {
    out[silo.id] = {
      cleansePct: CLEANSE_SEED[i] ?? 50,
      shardCount: ((silo.id * 2) % 6) + 3,
      records: 120_000 + silo.id * 47_300,
    }
  })
  return out
}

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

  // 사일로 등록/해제 전파 (useSiloStore가 호출)
  ensureSiloData: (siloId: number) => void
  removeSiloData: (siloId: number) => void

  // 6.4 정제 제어
  cleanseSilo: (siloId: number) => void

  // 6.5 스케줄러 제어
  canRun: (id: string) => boolean
  runJob: (id: string) => void
  pauseJob: (id: string) => void

  // 파이프라인(작업) 등록/해제
  addJob: (input: NewJobInput) => void
  removeJob: (id: string) => void
}

let jobSeq = 1
const nextJobId = (): string => `job-u${jobSeq++}`

function depsSatisfied(jobs: Job[], job: Job): boolean {
  return job.dependsOn.every((depId) => jobs.find((j) => j.id === depId)?.state === 'done')
}

export const useDataStore = create<DataStore>((set, get) => ({
  dataBySilo: seedDataBySilo(),
  jobs: seedJobs(),

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

  cleanseSilo: (siloId) => {
    const current = get().dataBySilo[siloId]
    if (!current || current.cleansePct >= 100) return
    logToConsole('server', `[사일로 #${siloId}] 데이터 정제 작업을 시작합니다. (현재 ${current.cleansePct}%)`)

    const step = (): void => {
      const data = get().dataBySilo[siloId]
      if (!data) return
      const next = Math.min(100, data.cleansePct + CLEANSE_STEP_PCT)
      set((state) => ({
        dataBySilo: { ...state.dataBySilo, [siloId]: { ...data, cleansePct: next } },
      }))
      if (next >= 100) {
        logToConsole('success', `[사일로 #${siloId}] 데이터 정제 완료 (100%).`)
      } else {
        window.setTimeout(step, CLEANSE_STEP_MS)
      }
    }
    window.setTimeout(step, CLEANSE_STEP_MS)
  },

  canRun: (id) => {
    const jobs = get().jobs
    const job = jobs.find((j) => j.id === id)
    if (!job) return false
    return (job.state === 'queued' || job.state === 'failed') && depsSatisfied(jobs, job)
  },

  runJob: (id) => {
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
    const job = get().jobs.find((j) => j.id === id)
    if (!job || job.state !== 'running') return
    set((state) => ({
      jobs: state.jobs.map((j) => (j.id === id ? { ...j, state: 'queued' } : j)),
    }))
    logToConsole('system', `[${job.name}] 작업을 일시중지하여 대기열로 되돌렸습니다.`)
  },

  addJob: (input) => {
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
