import { useMemo, useState, type ReactNode } from 'react'
import {
  baselineKey,
  mapHistogram,
  mapParticipation,
  mapSiloBar,
  mapTimeseriesToLines,
  parseModelKey,
} from '@/api/mappers'
import { BaselineHistogram } from '@/components/visualization/BaselineHistogram'
import { LiveTopology } from '@/components/visualization/LiveTopology'
import { ParticipationHeatmap } from '@/components/visualization/ParticipationHeatmap'
import { SiloBarChart } from '@/components/visualization/SiloBarChart'
import { SiloTrendChart } from '@/components/visualization/SiloTrendChart'
import {
  useVisualizationData,
  type ResourceMetric,
  type TrendMetric,
  type VizChartKey,
  type VizSnapshot,
} from '@/hooks/useVisualizationData'
import { layoutVizTopology } from '@/lib/vizTopology'
import { UNCONFIGURED_API_MESSAGE, resolveUiDataMode } from '@/lib/uiMode'
import { useModelStore } from '@/store/useModelStore'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { ModelVersion } from '@/types/simulation'

interface TrendMetricMeta {
  value: TrendMetric
  label: string
  yTitle: string
  /** 서버 값 → 표시 단위 (accuracy 0~1 → %) */
  scale: number
}

const TREND_METRICS: TrendMetricMeta[] = [
  { value: 'accuracy', label: '정확도', yTitle: '정확도 (%)', scale: 100 },
  { value: 'latency_ms', label: '지연', yTitle: '지연 (ms)', scale: 1 },
  { value: 'throughput_rps', label: '처리량', yTitle: '처리량 (req/s)', scale: 1 },
]

const RESOURCE_METRICS: Array<{ value: ResourceMetric; label: string }> = [
  { value: 'cpu_pct', label: 'CPU' },
  { value: 'mem_pct', label: '메모리' },
  { value: 'gpu_pct', label: 'GPU' },
  { value: 'disk_pct', label: '디스크' },
]

type BarMode = 'samples' | 'resource'

const BAR_MODES: Array<{ value: BarMode; label: string }> = [
  { value: 'samples', label: '표본수' },
  { value: 'resource', label: '자원 사용률' },
]

// --- 공통 조각 ------------------------------------------------------------------

interface VizCardProps {
  icon: string
  title: string
  desc: string
  toolbar?: ReactNode
  children: ReactNode
}

function VizCard({ icon, title, desc, toolbar, children }: VizCardProps) {
  return (
    <div className="glass-panel content-card viz-card">
      <div className="card-header">
        <h3>
          <i className={`fa-solid ${icon}`} /> {title}
        </h3>
        <span className="desc">{desc}</span>
      </div>
      <div className="card-body">
        {toolbar && <div className="viz-toolbar">{toolbar}</div>}
        {children}
      </div>
    </div>
  )
}

interface FilterGroupProps<T extends string> {
  label: string
  options: Array<{ value: T; label: string }>
  value: T
  onChange: (value: T) => void
}

function FilterGroup<T extends string>({ label, options, value, onChange }: FilterGroupProps<T>) {
  return (
    <div className="filter-group" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={`filter-btn${value === o.value ? ' active' : ''}`}
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

interface EmptyProps {
  children: ReactNode
}

function Empty({ children }: EmptyProps) {
  return <div className="deploy-empty">{children}</div>
}

/** 불러오는 중 · 실패 · 빈 데이터 · 차트 중 하나를 고른다 (emptyText가 있으면 빈 데이터) */
function slot(
  snapshot: VizSnapshot | null,
  key: VizChartKey,
  emptyText: string | null,
  render: () => ReactNode,
  unconfiguredMessage?: string | null,
): ReactNode {
  if (unconfiguredMessage) return <Empty>{unconfiguredMessage}</Empty>
  if (!snapshot || snapshot.loading.includes(key)) return <Empty>데이터를 불러오는 중입니다.</Empty>
  if (snapshot.failed.includes(key)) {
    return <Empty>데이터를 불러오지 못했습니다. 서버 연결을 확인해 주세요. 10초마다 다시 시도합니다.</Empty>
  }
  if (emptyText) return <Empty>{emptyText}</Empty>
  return render()
}

// --- 카드 5종 -------------------------------------------------------------------

interface TrendCardProps {
  snapshot: VizSnapshot | null
  models: ModelVersion[]
  model: ModelVersion | undefined
  onModelChange: (id: string) => void
  metric: TrendMetricMeta
  onMetricChange: (metric: TrendMetric) => void
  unconfiguredMessage?: string | null
}

function TrendCard({ snapshot, models, model, onModelChange, metric, onMetricChange, unconfiguredMessage }: TrendCardProps) {
  const raw = snapshot?.data.trend
  const trend = useMemo(() => (raw ? mapTimeseriesToLines(raw, metric.scale) : null), [raw, metric.scale])
  const toolbar = (
    <>
      <div className="viz-select select-wrapper">
        <select
          aria-label="모델 선택"
          value={model?.id ?? ''}
          onChange={(e) => onModelChange(e.target.value)}
          disabled={models.length === 0}
        >
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.project} {m.version}
            </option>
          ))}
        </select>
      </div>
      <FilterGroup label="지표 선택" options={TREND_METRICS} value={metric.value} onChange={onMetricChange} />
    </>
  )
  return (
    <VizCard icon="fa-chart-line" title="사일로별 성능 추이" desc="Per-silo metric trend over time." toolbar={toolbar}>
      {!model ? (
        <Empty>모델을 등록하면 사일로별 성능 추이를 볼 수 있습니다.</Empty>
      ) : (
        slot(snapshot, 'trend', trend?.series.length ? null : '사일로에서 지표 수집을 시작하면 추이가 표시됩니다.', () =>
          trend && <SiloTrendChart input={trend} yTitle={metric.yTitle} />,
        unconfiguredMessage)
      )}
    </VizCard>
  )
}

interface SnapshotCardProps {
  snapshot: VizSnapshot | null
  unconfiguredMessage?: string | null
}

function ParticipationCard({ snapshot, unconfiguredMessage }: SnapshotCardProps) {
  const raw = snapshot?.data.participation
  const grid = useMemo(() => (raw ? mapParticipation(raw) : null), [raw])
  return (
    <VizCard icon="fa-table-cells" title="사일로 × 라운드 참여 매트릭스" desc="Which silos contributed to each training round.">
      {slot(snapshot, 'participation', grid?.columns.length ? null : '학습 라운드를 시작하면 사일로별 참여 현황이 표시됩니다.', () =>
        grid && <ParticipationHeatmap grid={grid} />,
      unconfiguredMessage)}
    </VizCard>
  )
}

interface BarCardProps {
  snapshot: VizSnapshot | null
  mode: BarMode
  onModeChange: (mode: BarMode) => void
  resource: ResourceMetric
  onResourceChange: (metric: ResourceMetric) => void
  unconfiguredMessage?: string | null
}

function BarCard({ snapshot, mode, onModeChange, resource, onResourceChange, unconfiguredMessage }: BarCardProps) {
  const roundBar = snapshot?.data.roundBar
  const resourceBar = snapshot?.data.resourceBar
  const isSamples = mode === 'samples'
  const input = useMemo(() => {
    const payload = isSamples ? roundBar?.payload : resourceBar
    return payload ? mapSiloBar(payload) : null
  }, [isSamples, roundBar, resourceBar])
  const resourceLabel = RESOURCE_METRICS.find((m) => m.value === resource)?.label ?? ''
  const toolbar = (
    <>
      <FilterGroup label="비교 항목" options={BAR_MODES} value={mode} onChange={onModeChange} />
      {!isSamples && (
        <FilterGroup label="자원 선택" options={RESOURCE_METRICS} value={resource} onChange={onResourceChange} />
      )}
      {isSamples && roundBar && <span className="viz-caption">라운드 {roundBar.roundId.slice(0, 8)}</span>}
    </>
  )
  const emptyText = input?.labels.length
    ? null
    : isSamples
      ? '학습 라운드를 완료하면 사일로별 표본수가 표시됩니다.'
      : '사일로 자원 수집을 시작하면 사용률이 표시됩니다.'
  return (
    <VizCard
      icon="fa-chart-column"
      title="사일로 비교"
      desc={isSamples ? 'Sample contribution in the latest completed round.' : 'Current resource usage per silo.'}
      toolbar={toolbar}
    >
      {slot(snapshot, isSamples ? 'roundBar' : 'resourceBar', emptyText, () =>
        input && (
          <SiloBarChart
            input={input}
            yTitle={isSamples ? '표본수' : `${resourceLabel} 사용률 (%)`}
            yMax={isSamples ? undefined : 100}
          />
        ),
      unconfiguredMessage)}
    </VizCard>
  )
}

interface HistogramCardProps {
  snapshot: VizSnapshot | null
  selected: string | null
  onBaselineChange: (key: string) => void
  unconfiguredMessage?: string | null
}

function HistogramCard({ snapshot, selected, onBaselineChange, unconfiguredMessage }: HistogramCardProps) {
  const baselines = snapshot?.data.baselines ?? []
  const shown = snapshot?.data.histogram
  const input = useMemo(() => (shown ? mapHistogram(shown.payload) : null), [shown])
  const feature = baselines.find((b) => baselineKey(b) === shown?.key)?.feature ?? ''
  const toolbar = (
    <div className="viz-select select-wrapper">
      <select
        aria-label="기준 분포 선택"
        value={shown?.key ?? selected ?? ''}
        onChange={(e) => onBaselineChange(e.target.value)}
        disabled={baselines.length === 0}
      >
        {baselines.map((b) => (
          <option key={baselineKey(b)} value={baselineKey(b)}>
            {b.model_name} {b.version} · {b.feature}
          </option>
        ))}
      </select>
    </div>
  )
  return (
    <VizCard icon="fa-chart-simple" title="기준 분포" desc="Baseline feature distribution used for drift detection." toolbar={toolbar}>
      {slot(snapshot, 'histogram', input?.values.length ? null : '기준 분포를 등록하면 피처별 분포가 표시됩니다.', () =>
        input && <BaselineHistogram input={input} feature={feature} />,
      unconfiguredMessage)}
    </VizCard>
  )
}

function TopologyCard({ snapshot, unconfiguredMessage }: SnapshotCardProps) {
  const raw = snapshot?.data.topology
  const layout = useMemo(() => (raw ? layoutVizTopology(raw) : null), [raw])
  return (
    <VizCard icon="fa-diagram-project" title="연합 토폴로지" desc="Central server, groups, aggregators, silos and running deployments.">
      {slot(snapshot, 'topology', layout?.nodes.length ? null : '사일로를 등록하면 연합 구성이 표시됩니다.', () =>
        layout && <LiveTopology layout={layout} />,
      unconfiguredMessage)}
    </VizCard>
  )
}

// --- 화면 -----------------------------------------------------------------------

export function VisualizationView() {
  const mockEnabled = useSimulationStore((s) => s.mockEnabled)
  const models = useModelStore((s) => s.models)

  // 순수 로컬 UI 선택 (AGENTS.md §2 예외)
  const [modelId, setModelId] = useState<string | null>(null)
  const [trendMetric, setTrendMetric] = useState<TrendMetric>('accuracy')
  const [barMode, setBarMode] = useState<BarMode>('samples')
  const [resourceMetric, setResourceMetric] = useState<ResourceMetric>('cpu_pct')
  const [selectedBaseline, setSelectedBaseline] = useState<string | null>(null)

  const model =
    models.find((m) => m.id === modelId) ?? models.find((m) => m.status === 'deployed') ?? models[0]
  const modelRef = model ? mockEnabled ? { name: model.project, version: model.version } : parseModelKey(model.id) : null
  const { snapshot } = useVisualizationData({
    modelName: modelRef?.name ?? null,
    modelVersion: modelRef?.version ?? null,
    trendMetric,
    resourceMetric,
    baselineKey: selectedBaseline,
  })

  const uiMode = resolveUiDataMode(mockEnabled)
  const unconfiguredMessage = uiMode === 'unconfigured' ? UNCONFIGURED_API_MESSAGE : null

  return (
    <div className="tab-pane">
      <TrendCard
        snapshot={snapshot}
        models={models}
        model={model}
        onModelChange={setModelId}
        metric={TREND_METRICS.find((m) => m.value === trendMetric) ?? TREND_METRICS[0]}
        onMetricChange={setTrendMetric}
        unconfiguredMessage={unconfiguredMessage}
      />
      <ParticipationCard snapshot={snapshot} unconfiguredMessage={unconfiguredMessage} />
      <div className="viz-grid">
        <BarCard
          snapshot={snapshot}
          mode={barMode}
          onModeChange={setBarMode}
          resource={resourceMetric}
          onResourceChange={setResourceMetric}
          unconfiguredMessage={unconfiguredMessage}
        />
        <HistogramCard snapshot={snapshot} selected={selectedBaseline} onBaselineChange={setSelectedBaseline} unconfiguredMessage={unconfiguredMessage} />
      </div>
      <TopologyCard snapshot={snapshot} unconfiguredMessage={unconfiguredMessage} />
    </div>
  )
}
