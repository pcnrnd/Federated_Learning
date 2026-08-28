import type { ResourceLimit, ResourceUsageSummary, MetricSample } from '@/api/client'
import type { ChartPoint, MonitorPoint, Silo } from '@/types/simulation'

/**
 * 서버 응답 → UI 스토어 형태 변환 (순수 함수).
 * 계약: docs/specs/2026-08-21-p0-api-contract.md
 */

const DEFAULT_THRESHOLDS = { cpu: 85, mem: 80, disk: 90 } as const

/** "silo-3" → 3. 끝자리 숫자가 없으면 목록 순번+1000으로 충돌을 피한다 */
export function siloIdToNumber(siloId: string, index: number): number {
  const match = /(\d+)\s*$/.exec(siloId)
  return match ? Number(match[1]) : 1000 + index
}

export function mapUsageToSilos(
  usage: readonly ResourceUsageSummary[],
  limits: readonly ResourceLimit[],
): Silo[] {
  const limitBySilo = new Map(limits.map((l) => [l.silo_id, l]))
  return usage.map((u, i) => {
    const limit = limitBySilo.get(u.silo_id)
    return {
      id: siloIdToNumber(u.silo_id, i),
      name: u.silo_id,
      endpoint: '(실서버)',
      collectIntervalSec: 0,
      cpu: Math.round(u.cpu_pct),
      mem: Math.round(u.mem_pct),
      disk: Math.round(u.disk_pct ?? 0),
      thresholds: {
        cpu: limit?.cpu_pct_max ?? DEFAULT_THRESHOLDS.cpu,
        mem: limit?.mem_pct_max ?? DEFAULT_THRESHOLDS.mem,
        disk: limit?.disk_pct_max ?? DEFAULT_THRESHOLDS.disk,
      },
    }
  })
}

/** 같은 timestamp의 사일로 값들을 한 라운드로 묶어 평균한다 */
function averageByTimestamp(samples: readonly MetricSample[]): number[] {
  const byTs = new Map<string, number[]>()
  for (const s of samples) {
    const bucket = byTs.get(s.timestamp)
    if (bucket) bucket.push(s.value)
    else byTs.set(s.timestamp, [s.value])
  }
  return [...byTs.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, values]) => values.reduce((sum, v) => sum + v, 0) / values.length)
}

export function mapMetricsToChartPoints(accuracy: readonly MetricSample[]): ChartPoint[] {
  // 서버 accuracy는 0~1 스케일 → UI는 % (부동소수점 잔여 오차 반올림)
  return averageByTimestamp(accuracy).map((v, i) => ({
    round: i,
    accuracy: Math.round(v * 10000) / 100,
    loss: 0, // 서버에 loss 지표 없음 — P2에서 라운드 집계 결과로 대체
  }))
}

export function mapMetricsToMonitorPoints(
  throughput: readonly MetricSample[],
  latency: readonly MetricSample[],
): MonitorPoint[] {
  const rps = averageByTimestamp(throughput)
  const ms = averageByTimestamp(latency)
  const count = Math.max(rps.length, ms.length)
  return Array.from({ length: count }, (_, i) => ({
    round: i,
    throughput: Math.round((rps[i] ?? 0) * 10) / 10,
    latency: Math.round((ms[i] ?? 0) * 10) / 10,
    drift: 0, // 드리프트 조회는 P0 범위 밖
  }))
}
