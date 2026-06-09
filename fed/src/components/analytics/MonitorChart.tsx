import {
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
  type ChartOptions,
} from 'chart.js'
import { useEffect, useMemo, useRef } from 'react'
import { Line } from 'react-chartjs-2'
import { MONITOR_PREVIEW_POINTS } from '@/constants/simulation'
import { getChartTheme, type ChartTheme } from '@/lib/chartTheme'
import { useSimulationStore } from '@/store/useSimulationStore'

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
  Filler,
)

function buildChartOptions(t: ChartTheme): ChartOptions<'line'> {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 400 },
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        position: 'top',
        labels: { font: { size: 11 }, color: t.text, usePointStyle: true },
      },
      tooltip: {
        mode: 'index',
        intersect: false,
        backgroundColor: t.tooltipBg,
        titleColor: t.tooltipTitle,
        bodyColor: t.tooltipBody,
        borderColor: t.tooltipBorder,
        borderWidth: 1,
      },
    },
    scales: {
      x: {
        grid: { color: t.grid },
        ticks: { color: t.text },
        title: {
          display: true,
          text: '연합 학습 라운드 (Global Rounds)',
          color: t.text,
          font: { size: 11 },
        },
      },
      yThroughput: {
        type: 'linear',
        position: 'left',
        min: 0,
        grid: { color: t.grid },
        ticks: { color: t.text },
        title: { display: true, text: '처리량 (req/s)', color: t.text, font: { size: 11 } },
      },
      yLatency: {
        type: 'linear',
        position: 'right',
        min: 0,
        grid: { drawOnChartArea: false },
        ticks: { color: t.text },
        title: { display: true, text: '처리시간 (ms)', color: t.text, font: { size: 11 } },
      },
    },
  }
}

export function MonitorChart() {
  const monitorPoints = useSimulationStore((s) => s.monitorPoints)
  const isRunning = useSimulationStore((s) => s.isRunning)
  const theme = useSimulationStore((s) => s.theme)
  const chartRef = useRef<ChartJS<'line'>>(null)

  const showPreview = monitorPoints.length === 0 && !isRunning

  // 테마 전환 시 토큰에서 색을 다시 읽어 차트를 재구성한다.
  const options = useMemo(() => buildChartOptions(getChartTheme()), [theme])

  const data = useMemo(() => {
    const source = showPreview ? MONITOR_PREVIEW_POINTS : monitorPoints
    const labels = source.map((p) => p.round)
    return {
      labels,
      datasets: [
        {
          label: showPreview ? '예상 처리량' : '처리량 (req/s)',
          data: source.map((p) => p.throughput),
          borderColor: showPreview ? 'rgba(168, 85, 247, 0.35)' : '#a855f7',
          backgroundColor: showPreview ? 'rgba(168, 85, 247, 0.04)' : 'rgba(168, 85, 247, 0.15)',
          borderWidth: showPreview ? 1.5 : 2.5,
          borderDash: showPreview ? ([6, 4] as number[]) : undefined,
          fill: true,
          tension: 0.35,
          pointRadius: showPreview ? 3 : 5,
          pointHoverRadius: 7,
          pointBackgroundColor: showPreview ? 'rgba(168, 85, 247, 0.45)' : '#a855f7',
          yAxisID: 'yThroughput',
        },
        {
          label: showPreview ? '예상 처리시간' : '처리시간 (ms)',
          data: source.map((p) => p.latency),
          borderColor: showPreview ? 'rgba(245, 158, 11, 0.35)' : '#f59e0b',
          backgroundColor: showPreview ? 'rgba(245, 158, 11, 0.03)' : 'rgba(245, 158, 11, 0.08)',
          borderWidth: showPreview ? 1.5 : 2.5,
          borderDash: showPreview ? ([6, 4] as number[]) : undefined,
          fill: true,
          tension: 0.35,
          pointRadius: showPreview ? 3 : 5,
          pointHoverRadius: 7,
          pointBackgroundColor: showPreview ? 'rgba(245, 158, 11, 0.45)' : '#f59e0b',
          yAxisID: 'yLatency',
        },
      ],
    }
  }, [monitorPoints, showPreview])

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      chartRef.current?.resize()
      chartRef.current?.update('none')
    })
    return () => window.cancelAnimationFrame(frame)
  }, [monitorPoints, showPreview])

  return (
    <div className="analytics-chart-box">
      <Line ref={chartRef} data={data} options={options} />
    </div>
  )
}
