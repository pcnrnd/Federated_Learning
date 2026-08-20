import { useMemo } from 'react'
import { useMonitoringStore } from '@/store/useMonitoringStore'
import { useModelStore } from '@/store/useModelStore'

/** 드리프트·재학습 임계치 및 자동 재학습 설정 패널 (기본 접힘). */
export function DriftSettingsPanel() {
  const expanded = useMonitoringStore((s) => s.settingsExpanded)
  const toggleExpanded = useMonitoringStore((s) => s.toggleSettingsExpanded)
  const warnThreshold = useMonitoringStore((s) => s.warnThreshold)
  const alertThreshold = useMonitoringStore((s) => s.alertThreshold)
  const autoRetrain = useMonitoringStore((s) => s.autoRetrain)
  const retrainModelId = useMonitoringStore((s) => s.retrainModelId)
  const setWarnThreshold = useMonitoringStore((s) => s.setWarnThreshold)
  const setAlertThreshold = useMonitoringStore((s) => s.setAlertThreshold)
  const setAutoRetrain = useMonitoringStore((s) => s.setAutoRetrain)
  const setRetrainModelId = useMonitoringStore((s) => s.setRetrainModelId)

  // 원본 배열을 select한 뒤 useMemo로 파생한다.
  // selector에서 .filter()로 새 배열을 반환하면 zustand v5(Object.is 비교) +
  // useSyncExternalStore가 매 렌더마다 다른 참조를 감지해 무한 렌더 루프에 빠진다.
  const models = useModelStore((s) => s.models)
  const deployedModels = useMemo(
    () => models.filter((m) => m.status === 'deployed'),
    [models],
  )
  const thresholdInvalid = warnThreshold >= alertThreshold

  return (
    <div className={`drift-settings-panel${expanded ? ' expanded' : ''}`}>
      <button
        type="button"
        className="drift-settings-header"
        onClick={toggleExpanded}
        aria-expanded={expanded}
      >
        <span className="drift-settings-title">
          <i className="fa-solid fa-sliders" /> 드리프트·재학습 설정
        </span>
        <i className={`fa-solid fa-chevron-down drift-settings-chevron${expanded ? ' open' : ''}`} />
      </button>

      {expanded && (
        <div className="drift-settings-body">
          <div className="drift-settings-grid">
            <div className="control-group">
              <label htmlFor="drift-warn-threshold">경고 임계 (%)</label>
              <input
                id="drift-warn-threshold"
                type="number"
                className="model-input"
                min={0}
                max={100}
                value={warnThreshold}
                onChange={(e) => setWarnThreshold(Number(e.target.value))}
              />
            </div>
            <div className="control-group">
              <label htmlFor="drift-alert-threshold">경보 임계 (%)</label>
              <input
                id="drift-alert-threshold"
                type="number"
                className="model-input"
                min={0}
                max={100}
                value={alertThreshold}
                onChange={(e) => setAlertThreshold(Number(e.target.value))}
              />
            </div>
          </div>

          {thresholdInvalid && (
            <p className="drift-settings-error" role="alert">
              <i className="fa-solid fa-circle-exclamation" /> 경고 임계는 경보 임계보다 낮아야 합니다.
            </p>
          )}

          <div className="drift-settings-row">
            <label className="drift-toggle" htmlFor="drift-auto-retrain">
              <input
                id="drift-auto-retrain"
                type="checkbox"
                checked={autoRetrain}
                onChange={(e) => setAutoRetrain(e.target.checked)}
              />
              <span className="drift-toggle-track" aria-hidden="true" />
              <span className="drift-toggle-label">자동 재학습</span>
            </label>
            <span className="drift-settings-hint">
              경보 임계 초과 시 실험 버전을 자동 생성합니다.
            </span>
          </div>

          <div className="control-group">
            <label htmlFor="drift-retrain-model">재학습 대상 모델</label>
            <div className="select-wrapper">
              <select
                id="drift-retrain-model"
                value={retrainModelId}
                onChange={(e) => setRetrainModelId(e.target.value as string | 'auto')}
              >
                <option value="auto">자동 (첫 번째 배포 모델)</option>
                {deployedModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.project} {m.version}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
