import type { SiloDataFields } from '@/store/useDataStore'
import type { NodeState, Silo } from '@/types/simulation'

export type DisplayMetricKey = 'acc' | 'loss' | 'delay' | 'size' | 'cpu' | 'distribution'

export interface DisplayNode extends NodeState {
  metricUnavailable?: Partial<Record<DisplayMetricKey, boolean>>
  cleanseProgressPct?: number | null
}

function shortLabel(name: string): string {
  const trimmed = name.trim()
  if (trimmed.length <= 10) return trimmed
  return `${trimmed.slice(0, 9)}…`
}

export function silosToDisplayNodes(
  silos: readonly Silo[],
  dataBySilo: Readonly<Record<number, SiloDataFields>>,
): DisplayNode[] {
  return silos.map((silo) => {
    const pipeline = dataBySilo[silo.id]
    const hasRecords = pipeline !== undefined && pipeline.records > 0
    return {
      id: silo.id,
      name: silo.name,
      shortName: shortLabel(silo.name),
      size: pipeline?.records ?? 0,
      delay: 0,
      mult: 1,
      acc: 0,
      loss: 0,
      cpu: silo.cpu ?? 0,
      status: 'idle',
      normalPct: 0,
      abnormalPct: 0,
      enabled: true,
      parentId: silo.parentId,
      cleanseProgressPct: pipeline ? pipeline.cleansePct : null,
      metricUnavailable: {
        acc: true,
        loss: true,
        delay: true,
        size: !hasRecords && pipeline === undefined,
        cpu: silo.cpu === null,
        distribution: true,
      },
    }
  })
}
