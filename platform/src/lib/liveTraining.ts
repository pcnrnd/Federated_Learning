export function liveTrainingRequest(draft: Record<string, string>) {
  const features = draft.features.split(',').map((value) => value.trim()).filter(Boolean)
  if (draft.initial.split(',').some((value) => !value.trim())) throw new Error('빈 초기 파라미터는 사용할 수 없습니다')
  const initial = draft.initial.split(',').map((value) => Number(value.trim()))
  const settings = { l2: Number(draft.l2), step_size: Number(draft.step_size), steps: Number(draft.steps) }
  if (features.length + 1 !== initial.length || [...initial, ...Object.values(settings)].some((n) => !Number.isFinite(n))) {
    throw new Error('특징 수+편향과 같은 개수의 유한한 초기값 및 학습 설정이 필요합니다')
  }
  if (!features.length || new Set(features).size !== features.length || features.includes(draft.target)
      || settings.l2 < 0 || settings.step_size <= 0 || !Number.isInteger(settings.steps) || settings.steps < 1) {
    throw new Error('특징/타깃과 학습 설정의 범위를 확인하세요')
  }
  return { job_id: draft.job_id, model_name: draft.model_name, version: draft.version,
    group_id: draft.group_id, cleaning_job_id: draft.cleaning_job_id, schedule_kind: 'chain',
    max_rounds: Number(draft.max_rounds), min_contributions: Number(draft.min_contributions),
    learning: { solver: 'ridge_gradient_v1', features, target: draft.target,
      initial_parameters: initial, ...settings } }
}
