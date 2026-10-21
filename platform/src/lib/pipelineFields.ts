/** LiveCleaningScheduler / UnifiedPipelineForm 공통 정제 필드 정의 */
export const CLEANING_FORM_FIELDS = [
  ["job_id", "작업 ID", "text"],
  ["recipe_name", "등록 레시피 이름", "text"],
  ["recipe_version", "레시피 버전", "text"],
  ["dataset_label", "로컬 데이터셋", "text"],
  ["scheduled_at", "최초 실행 시각 (빈 값: 즉시)", "datetime-local"],
  ["interval_seconds", "반복 주기 (초, 빈 값: 1회)", "number"],
  ["max_occurrences", "최대 회차 (빈 값: 계속)", "number"],
  ["depends_on", "선행 정제 ID (쉼표로 구분)", "text"],
  ["max_attempts", "최대 시도 수", "number"],
  ["retry_backoff_seconds", "재시도 대기 (초)", "number"],
  ["timeout_seconds", "시도 시간 한도 (초)", "number"],
  ["partitions", "내부 분할 수", "number"],
  ["parallelism", "내부 동시 실행 한도", "number"],
] as const

export const TRAINING_FORM_FIELDS = [
  ["job_id", "학습 작업 ID"],
  ["model_name", "등록 모델 이름"],
  ["version", "등록 모델 버전"],
  ["features", "특징 순서 (쉼표 구분)"],
  ["target", "타깃 열"],
  ["initial", "최초 파라미터 (특징 순서, 마지막 편향)"],
  ["l2", "Ridge 정규화"],
  ["step_size", "학습률"],
  ["steps", "로컬 업데이트 횟수"],
  ["max_rounds", "연속 라운드 수"],
  ["min_contributions", "중앙 대표 정족수"],
] as const

export const initialTrainingDraftRecord = (): Record<string, string> => ({
  job_id: "",
  model_name: "",
  version: "1.0.0",
  group_id: "",
  cleaning_job_id: "",
  features: "x1,x2,x3",
  target: "y",
  initial: "0,0,0,0",
  l2: "0.001",
  step_size: "0.0001",
  steps: "1",
  max_rounds: "2",
  min_contributions: "1",
})

export const MAIN_MODEL_FIELD_IDS = [
  "new-model-project",
  "new-model-version",
  "new-model-algorithm",
  "new-model-accuracy",
  "new-model-rounds",
  "new-model-note",
  "live-model-source",
  "live-model-round",
  "live-model-name",
  "live-model-weights",
] as const

export const MAIN_PIPELINE_FIELD_IDS = [
  "new-job-name",
  "new-job-schedule",
  "new-job-target",
  "pipe-cleaning-advanced",
  "pipe-training-advanced",
] as const

export const PIPE_CLEANING_FIELD_IDS = CLEANING_FORM_FIELDS.map(([key]) => `pipe-cleaning-${key}`)

export const PIPE_TRAINING_FIELD_IDS = TRAINING_FORM_FIELDS.map(([key]) => `pipe-training-${key}`)

export const CONTROL_TRAINING_FIELD_IDS = TRAINING_FORM_FIELDS.map(([key]) => `control-training-${key}`)

export const CONTROL_CLEANING_FIELD_IDS = CLEANING_FORM_FIELDS.map(([key]) => `control-cleaning-${key}`)

export const RETRAINING_FIELD_IDS = [
  "retrain-config-select",
  "retrain-baseline-select",
  "retrain-group-select",
  "retrain-dataset-input",
  "retrain-rounds-input",
  "retrain-enabled-checkbox",
  "retrain-automatic-checkbox",
] as const

export const LIVE_DRIFT_POLICY_FIELD_IDS = [
  "live-drift-warning",
  "live-drift-critical",
  "live-drift-minimum",
  "live-drift-maxAge",
] as const
