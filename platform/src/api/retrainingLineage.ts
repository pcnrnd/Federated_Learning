import { apiGet, type CleaningJobApi, type TrainingJobApi } from '@/api/client'

export type LineageKind = 'cleaning' | 'training' | 'result'
export const lineageKey = (kind: LineageKind, id: string) => JSON.stringify([kind, id])

/** 인증된 클라이언트로 조회하되 상세 화면에는 상태/집계값만 전달한다. */
export async function fetchLineage(kind: LineageKind, id: string): Promise<string[]> {
  const key = encodeURIComponent(id)
  if (kind === 'cleaning') {
    const job = await apiGet<CleaningJobApi>(`/api/cleaning-jobs/${key}`)
    return [`정제 상태: ${job.status}`, `행 수: ${job.total_rows_in} → ${job.total_rows_out}`]
  }
  if (kind === 'training') {
    const job = await apiGet<TrainingJobApi>(`/api/training-jobs/${key}`)
    return [`학습 상태: ${job.status}`, `완료 라운드: ${job.rounds_completed} / ${job.max_rounds}`]
  }
  const result = await apiGet<{ format: string; total_samples: number; parameter_dim: number }>(`/api/training-rounds/${key}/result`)
  return [`결과 형식: ${result.format}`, `집계 표본 수: ${result.total_samples}`, `파라미터 수: ${result.parameter_dim}`]
}
