import { useMemo } from 'react'
import { isLiveConfigured } from '@/api/client'
import { resolveUiDataMode } from '@/lib/uiMode'
import { useMonitoringStore } from '@/store/useMonitoringStore'
import { useModelStore } from '@/store/useModelStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import { LiveDriftPolicySection } from './LiveDriftPolicySection'

export function DriftSettingsPanel() {
  const mockEnabled = useSimulationStore((state) => state.mockEnabled)
  const mode = resolveUiDataMode(mockEnabled)
  const livePolicyDisabled = mode !== 'live' || !isLiveConfigured()
  return (
    <>
      <DemoDriftSettingsPanel demoOnly={mode !== 'demo'} />
      <LiveDriftPolicySection disabled={livePolicyDisabled} />
    </>
  )
}

function DemoDriftSettingsPanel({ demoOnly }: { demoOnly?: boolean }) {
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
          {demoOnly && (
            <p className="desc">데모 전용 임계치입니다. 실서버 PSI 정책은 아래 실제 비교 정책 섹션을 사용하세요.</p>
          )}
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
                disabled={demoOnly}
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
                disabled={demoOnly}
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
                disabled={demoOnly}
                onChange={(e) => setAutoRetrain(e.target.checked)}
              />
              <span className="drift-toggle-track" aria-hidden="true" />
              <span className="drift-toggle-label">자동 재학습</span>
            </label>
          </div>

          <div className="control-group">
            <label htmlFor="drift-retrain-model">재학습 대상 모델</label>
            <div className="select-wrapper">
              <select
                id="drift-retrain-model"
                value={retrainModelId}
                disabled={demoOnly}
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
