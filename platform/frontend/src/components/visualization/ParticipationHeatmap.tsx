import type { CSSProperties } from 'react'
import type { ParticipationStatus, TrainingRoundSummary } from '@/api/client'
import type { ParticipationCell, ParticipationGrid } from '@/api/mappers'
import { siloColorVar } from '@/lib/chartTheme'

/** 칸 상태 — 색만으로 구분하지 않도록 칸 안에 글자를 함께 쓴다 */
const STATUS_META: Record<ParticipationStatus, { label: string; short: string }> = {
  contributed: { label: '제출 (표본수)', short: '' },
  via_aggregator: { label: '집계자 경유', short: '경유' },
  missing: { label: '미제출', short: '미제출' },
  pending: { label: '제출 대기', short: '대기' },
  not_member: { label: '라운드 멤버 아님', short: '—' },
}

const ROUND_STATUS_LABEL: Record<TrainingRoundSummary['status'], string> = {
  open: '진행 중',
  aggregating: '집계 중',
  completed: '완료',
  failed: '실패',
}

const LEGEND_ORDER: ParticipationStatus[] = [
  'contributed',
  'via_aggregator',
  'missing',
  'pending',
  'not_member',
]

function cellText(cell: ParticipationCell): string {
  return cell.value !== null ? cell.value.toLocaleString() : STATUS_META[cell.status].short
}

interface ParticipationHeatmapProps {
  grid: ParticipationGrid
}

/** 사일로 × 라운드 참여 매트릭스 (표 격자 히트맵). 제출 칸은 표본수가 많을수록 진하다 */
export function ParticipationHeatmap({ grid }: ParticipationHeatmapProps) {
  return (
    <>
      <div className="viz-legend" aria-label="칸 상태 범례">
        {LEGEND_ORDER.map((status) => (
          <span key={status} className="viz-legend-item">
            <span className={`viz-legend-cell viz-cell--${status}`} />
            {STATUS_META[status].label}
          </span>
        ))}
      </div>
      <div className="viz-heatmap-wrap">
        <table className="viz-heatmap">
          <thead>
            <tr>
              <th scope="col">사일로</th>
              {grid.columns.map((col) => (
                <th
                  key={col.roundId}
                  scope="col"
                  title={`${col.roundId}\n${col.createdAt}`}
                >
                  <span className="viz-heatmap-round">{col.label}</span>
                  <span className="viz-heatmap-round-status">
                    {col.status ? ROUND_STATUS_LABEL[col.status] : ''}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.rows.map((row) => (
              <tr key={row.siloId}>
                <th scope="row">
                  <span className="viz-swatch" style={{ background: siloColorVar(row.siloId) }} />
                  {row.siloId}
                </th>
                {row.cells.map((cell, i) => (
                  <td
                    key={grid.columns[i]?.roundId ?? i}
                    className={`viz-cell viz-cell--${cell.status}`}
                    style={
                      cell.status === 'contributed'
                        ? ({ '--viz-intensity': cell.intensity } as CSSProperties)
                        : undefined
                    }
                    title={`${row.siloId} · ${grid.columns[i]?.label ?? ''} · ${STATUS_META[cell.status].label}${cell.value !== null ? ` ${cell.value.toLocaleString()}건` : ''}`}
                  >
                    {cellText(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">참여</th>
              {grid.columns.map((col) => (
                <td key={col.roundId}>
                  {col.participated}/{col.members}
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
    </>
  )
}
