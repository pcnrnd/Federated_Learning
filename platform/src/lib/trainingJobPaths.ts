/** 실제 학습 작업 mutation 경로 — job_id 특수문자는 encodeURIComponent로 이스케이프한다. */
export function trainingJobActionPath(
  jobId: string,
  action: 'pause' | 'resume' | 'cancel',
): string {
  return `/api/training-jobs/${encodeURIComponent(jobId)}/${action}`
}
