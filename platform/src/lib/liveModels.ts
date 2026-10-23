import type { PackageRecordApi } from '@/api/client'
import { modelKey } from '@/api/mappers'
import type { LiveModelDraft, ModelPackage } from '@/types/simulation'

/** 서버의 실제 결과 또는 저장된 artifact만 등록한다. 가중치/성과값을 만들지 않는다. */
export function liveModelRequest(draft: LiveModelDraft) {
  const version = draft.version.trim()
  if (version && !/^\d+\.\d+\.\d+$/.test(version)) throw new Error('버전은 1.0.0 형태로 입력하세요')
  if (draft.mode === 'training') {
    if (!draft.round_id) throw new Error('완료된 실제 학습 결과를 선택하세요')
    return { endpoint: '/api/models/from-training', body: { round_id: draft.round_id, ...(version ? { version } : {}) } }
  }
  if (!draft.name.trim() || !version || !draft.weights_path.trim()) throw new Error('모델 이름·버전·실제 artifact 경로를 입력하세요')
  return { endpoint: '/api/models', body: { framework: 'ridge', name: draft.name.trim(), version,
    weights_path: draft.weights_path.trim() } }
}

/** unbuilt/unknown은 완료가 아니다. 태그·digest·체크섬도 서버가 보고한 값만 표시한다. */
export function mapLivePackages(records: readonly PackageRecordApi[]): Record<string, ModelPackage> {
  return Object.fromEntries(records.map((record) => {
    const id = modelKey(record.model_name, record.version)
    return [id, { modelId: id, state: record.status === 'unbuilt' ? 'idle' : record.status,
      runtime: record.base_image ?? '', imageTag: record.image_tag ?? '',
      ...(record.built_at ? { builtAt: record.built_at } : {}),
      ...(record.image_digest ? { imageDigest: record.image_digest } : {}),
      ...(record.artifact_id ? { artifactId: record.artifact_id } : {}),
      ...(record.weights_checksum ? { weightsChecksum: record.weights_checksum } : {}),
      ...(record.error ? { error: record.error } : {}) } satisfies ModelPackage]
  }))
}
