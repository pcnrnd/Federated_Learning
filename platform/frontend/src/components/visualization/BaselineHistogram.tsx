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
import { accentColor, getChartTheme, vizAxes, vizTooltip } from '@/lib/chartTheme'
import { useSimulationStore } from '@/store/useSimulationStore'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip)

interface BaselineHistogramProps {
  input: BarChartInput
  /** x축 제목 — 피처명 */
  feature: string
}

/** 드리프트 판정의 기준 분포 (히스토그램) — 구간이 맞붙도록 막대 간격을 없앤다 */
export function BaselineHistogram({ input, feature }: BaselineHistogramProps) {
  const theme = useSimulationStore((s) => s.theme)

  const options = useMemo<ChartOptions<'bar'>>(() => {
    const t = getChartTheme()
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: { legend: { display: false }, tooltip: vizTooltip(t) },
      scales: vizAxes(t, feature, '건수'),
    }
  }, [theme, feature])

  const data = useMemo(
    () => ({
      labels: input.labels,
      datasets: [
        {
          label: '건수',
          data: input.values,
          backgroundColor: accentColor('primary'),
          borderRadius: 4,
          borderSkipped: 'start' as const,
          categoryPercentage: 1,
          barPercentage: 0.96,
        },
      ],
    }),
    [input, theme],
  )

  return (
    <div className="viz-chart-box">
      <Bar data={data} options={options} />
    </div>
  )
}
