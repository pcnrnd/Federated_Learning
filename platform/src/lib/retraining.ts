import type { RetrainingConfig, RetrainingConfigInput, RetrainingOption } from '@/types/simulation'

export interface RetrainingDraft {
  configId: string
  groupId: string
  dataset: string
  rounds: string
  enabled: boolean
  automatic: boolean
}

export const emptyRetrainingDraft = (): RetrainingDraft => ({ configId: '', groupId: '', dataset: '', rounds: '2', enabled: true, automatic: false })

export function retrainingDraft(config: RetrainingConfig): RetrainingDraft {
  const d = config.definition
  return { configId: d.config_id, groupId: d.group_id, dataset: d.dataset_label, rounds: String(d.max_rounds), enabled: d.enabled, automatic: d.auto_enabled }
}

export function retrainingPayload(draft: RetrainingDraft, options: RetrainingOption[]): RetrainingConfigInput | null {
  const selected = options.find((o) => o.config_id === draft.configId)
  const rounds = Number(draft.rounds)
  if (!selected?.policy_id || !draft.groupId || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(draft.dataset)
      || !Number.isInteger(rounds) || rounds < 2 || rounds > 100) return null
  return { config_id: selected.config_id, policy_id: selected.policy_id, group_id: draft.groupId,
    dataset_label: draft.dataset, max_rounds: rounds, enabled: draft.enabled, auto_enabled: draft.automatic }
}

export const retrainingStatus: Record<string, string> = {
  queued: '접수됨', cleaning_intent: '정제 준비', wait_cleaning: '정제 진행', training_intent: '학습 준비',
  training: '학습 진행', wait_registration: '새 모델 저장 확인', registered: '새 모델 등록 완료', failed: '실패',
}

export function retrainingError(code: string | null): string | null {
  if (!code) return null
  const messages: Record<string, string> = {
    cleaning_failed: '정제 작업이 실패하거나 취소되어 학습을 시작하지 않았습니다.',
    training_failed: '학습이 실패하거나 취소되어 재교육이 완료되지 않았습니다.',
    topology_changed: '저장한 참여 범위가 바뀌었습니다. 그룹과 설정을 확인하세요.',
    recipe_changed: '저장한 정제 규칙이 바뀌었습니다.',
    child_request_conflict: '같은 실행에 다른 설정이 연결되어 진행을 중단했습니다.',
  }
  return messages[code] ?? '저장·연결 또는 무결성 확인이 필요합니다. 기존 실행을 보존하고 있습니다.'
}
