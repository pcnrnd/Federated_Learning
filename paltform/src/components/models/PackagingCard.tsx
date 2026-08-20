import { useEffect, useState } from 'react'
import { RUNTIME_OPTIONS } from '@/constants/simulation'
import { useModelStore } from '@/store/useModelStore'
import type { ModelPackage, ModelVersion, PackageState } from '@/types/simulation'

interface PackagingCardProps {
  model: ModelVersion
  pkg?: ModelPackage
}

const PACKAGE_LABEL: Record<PackageState, string> = {
  idle: '대기',
  building: '빌드 중',
  built: '빌드됨',
}

const PACKAGE_CLASS: Record<PackageState, string> = {
  idle: 'pkg-badge-idle',
  building: 'pkg-badge-building',
  built: 'pkg-badge-built',
}

export function PackagingCard({ model, pkg }: PackagingCardProps) {
  const buildPackage = useModelStore((s) => s.buildPackage)
  const [runtime, setRuntime] = useState<string>(pkg?.runtime ?? RUNTIME_OPTIONS[0])

  // 모델 전환 시 해당 패키지의 런타임을 반영
  useEffect(() => {
    if (pkg?.runtime) setRuntime(pkg.runtime)
  }, [pkg?.runtime, model.id])

  const state: PackageState = pkg?.state ?? 'idle'
  const isBuilding = state === 'building'

  return (
    <div className="deploy-card glass-panel">
      <div className="deploy-card-head">
        <h4>
          <i className="fa-solid fa-box" /> 모델 패키징
        </h4>
        <span className={`pkg-badge ${PACKAGE_CLASS[state]}`}>{PACKAGE_LABEL[state]}</span>
      </div>

      <dl className="deploy-meta">
        <div>
          <dt>이미지 태그</dt>
          <dd className="mono">{pkg?.imageTag ?? '미생성'}</dd>
        </div>
        <div>
          <dt>빌드 시각</dt>
          <dd className="mono">{pkg?.builtAt ?? '—'}</dd>
        </div>
      </dl>

      <div className="control-group">
        <label htmlFor="pkg-runtime">컨테이너 런타임</label>
        <div className="select-wrapper">
          <select
            id="pkg-runtime"
            value={runtime}
            disabled={isBuilding}
            onChange={(e) => setRuntime(e.target.value)}
          >
            {RUNTIME_OPTIONS.map((rt) => (
              <option key={rt} value={rt}>
                {rt}
              </option>
            ))}
          </select>
        </div>
      </div>

      <button
        type="button"
        className="btn btn-secondary deploy-build-btn"
        disabled={isBuilding}
        onClick={() => buildPackage(model.id, runtime)}
      >
        {isBuilding ? (
          <>
            <i className="fa-solid fa-spinner fa-spin" /> 빌드 중...
          </>
        ) : (
          <>
            <i className="fa-solid fa-hammer" /> {state === 'built' ? '재빌드' : '패키징 빌드'}
          </>
        )}
      </button>
    </div>
  )
}
