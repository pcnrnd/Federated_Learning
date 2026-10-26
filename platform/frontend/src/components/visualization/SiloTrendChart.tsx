import {
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
  type ChartOptions,
} from 'chart.js'
import { useMemo } from 'react'
import { Line } from 'react-chartjs-2'
import type { LineChartInput } from '@/api/mappers'
import { getChartTheme, siloColor, vizAxes, vizTooltip } from '@/lib/chartTheme'
import { useSimulationStore } from '@/store/useSimulationStore'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend)

interface SiloTrendChartProps {
  input: LineChartInput
  yTitle: string
  connectGaps?: boolean
}

/** 사일로별 지표 추이 (선) — 사일로마다 고정색 */
export function SiloTrendChart({ input, yTitle, connectGaps = true }: SiloTrendChartProps) {
  const theme = useSimulationStore((s) => s.theme)

  const options = useMemo<ChartOptions<'line'>>(() => {
    const t = getChartTheme()
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      interaction: { mode: 'index', intersect: false },
      // 사일로마다 보고 시각이 달라 빈 칸이 생긴다 — 선은 이어 그린다
      spanGaps: connectGaps,
      plugins: {
        legend: {
          position: 'top',
          labels: { color: t.text, font: { size: 11 }, usePointStyle: true },
        },
        tooltip: vizTooltip(t),
      },
      scales: vizAxes(t, '수집 시각', yTitle, { beginAtZero: false }),
    }
  }, [theme, yTitle, connectGaps])

  const data = useMemo(
    () => ({
      labels: input.labels,
      datasets: input.series.map((s, index) => {
        const color = siloColor(s.siloId)
        return {
          label: s.siloId,
          data: s.values,
          borderColor: color,
          backgroundColor: color,
          borderWidth: 2,
          borderDash: [[], [7, 3], [2, 3], [10, 3, 2, 3]][index % 4],
          pointStyle: (['circle', 'rect', 'triangle', 'crossRot'] as const)[index % 4],
          pointRadius: 4,
          pointHoverRadius: 6,
          tension: 0.3,
        }
      }),
    }),
    // theme: 사일로 색 토큰을 테마 전환 뒤 다시 읽는다
    [input, theme],
  )

  return (
    <div className="viz-chart-box">
      <Line data={data} options={options} />
    </div>
  )
}
