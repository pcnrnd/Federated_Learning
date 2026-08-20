import { useMemo } from 'react'
import { useModelStore } from '@/store/useModelStore'
import type { ModelPackage, ModelVersion } from '@/types/simulation'

export interface DeployTarget {
  /** 배포 가능한(보관 제외) 모델 목록 */
  deployable: ModelVersion[]
  /** 현재 선택된 모델. 배포 가능한 모델이 없으면 null */
  selectedModel: ModelVersion | null
  activeId: string
  activePackage: ModelPackage | undefined
}

/**
 * 패키징·배포 섹션이 공유하는 대상 모델 선택 로직.
 * 두 섹션이 같은 `deployTargetId`를 보되 폴백 규칙이 어긋나지 않도록 한곳에 둔다.
 */
export function useDeployTarget(): DeployTarget {
  const models = useModelStore((s) => s.models)
  const packages = useModelStore((s) => s.packages)
  const deployTargetId = useModelStore((s) => s.deployTargetId)

  const deployable = useMemo(() => models.filter((m) => m.status !== 'archived'), [models])

  // 선택된 모델이 없거나 삭제/보관되면 첫 배포 가능 모델로 폴백
  const selectedModel = deployable.find((m) => m.id === deployTargetId) ?? deployable[0] ?? null
  const activeId = selectedModel?.id ?? ''

  return {
    deployable,
    selectedModel,
    activeId,
    activePackage: activeId ? packages[activeId] : undefined,
  }
}
