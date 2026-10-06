import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  LinearScale,
  Tooltip,
  type ChartOptions,
} from 'chart.js'
import { useMemo } from 'react'
import { Bar } from 'react-chartjs-2'
import type { BarChartInput } from '@/api/mappers'
import { getChartTheme, siloColor, vizAxes, vizTooltip } from '@/lib/chartTheme'
import { useSimulationStore } from '@/store/useSimulationStore'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip)

interface SiloBarChartProps {
  input: BarChartInput
  /** 툴팁·y축 제목 (예: '표본수', 'CPU 사용률 (%)') */
  yTitle: string
  yMax?: number
}

/** 사일로 간 비교 (막대) — 막대 색은 사일로 고정색, 사일로명은 x축 라벨이 맡는다 */
export function SiloBarChart({ input, yTitle, yMax }: SiloBarChartProps) {
  const theme = useSimulationStore((s) => s.theme)

  const options = useMemo<ChartOptions<'bar'>>(() => {
    const t = getChartTheme()
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: { legend: { display: false }, tooltip: vizTooltip(t) },
      scales: vizAxes(t, '사일로', yTitle, { max: yMax }),
    }
  }, [theme, yTitle, yMax])

  const data = useMemo(
    () => ({
      labels: input.labels,
      datasets: [
        {
          label: yTitle,
          data: input.values,
          backgroundColor: input.labels.map(siloColor),
          borderRadius: 4,
          borderSkipped: 'start' as const,
          maxBarThickness: 48,
        },
      ],
    }),
    [input, yTitle, theme],
  )

  return (
    <div className="viz-chart-box">
      <Bar data={data} options={options} />
    </div>
  )
}
