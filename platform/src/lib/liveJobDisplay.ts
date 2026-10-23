import type { TrainingJobApi } from '@/api/client'
import type { CleaningJobSummary, Job, JobState } from '@/types/simulation'

export type SchedulerJobKind = 'demo' | 'cleaning' | 'training'

export interface SchedulerRow extends Job {
  kind: SchedulerJobKind
}

const CLEANING_TO_JOB: Record<CleaningJobSummary['status'], JobState> = {
  pending: 'queued',
  running: 'running',
  completed: 'done',
  partial: 'failed',
  failed: 'failed',
}

const TRAINING_TO_JOB: Record<TrainingJobApi['status'], JobState> = {
  active: 'running',
  paused: 'running',
  completed: 'done',
  cancelled: 'failed',
  failed: 'failed',
}

function scheduleLabel(job: CleaningJobSummary): string {
  if (job.intervalSeconds) return `${job.intervalSeconds}s 주기`
  if (job.scheduledAt) return new Date(job.scheduledAt).toLocaleString()
  return '즉시 / 1회'
}

export function liveCleaningToSchedulerRows(jobs: readonly CleaningJobSummary[]): SchedulerRow[] {
  return jobs.map((job) => ({
    kind: 'cleaning',
    id: job.jobId,
    name: `${job.recipe} · ${job.datasetLabel}`,
    schedule: scheduleLabel(job),
    dependsOn: job.dependsOn ?? [],
    state: CLEANING_TO_JOB[job.status],
  }))
}

export function liveTrainingToSchedulerRows(jobs: readonly TrainingJobApi[]): SchedulerRow[] {
  return jobs.map((job) => ({
    kind: 'training',
    id: job.job_id,
    name: `${job.model_name}@${job.version} · 연합학습`,
    schedule: `라운드 ${job.rounds_completed}/${job.max_rounds}`,
    dependsOn: [],
    state: TRAINING_TO_JOB[job.status],
  }))
}

export function demoJobsToSchedulerRows(jobs: readonly Job[]): SchedulerRow[] {
  return jobs.map((job) => ({ ...job, kind: 'demo' as const }))
}
