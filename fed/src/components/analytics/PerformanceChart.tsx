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
import { CHART_PREVIEW_POINTS } from '@/constants/simulation'
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

ChartJS.defaults.color = '#9ca3af'
ChartJS.defaults.font.family = 'Inter, sans-serif'

const CHART_OPTIONS: ChartOptions<'line'> = {
  responsive: true,
  maintainAspectRatio: false,
  animation: {
    duration: 400,
  },
  interaction: {
    mode: 'index',
    intersect: false,
  },
  plugins: {
    legend: {
      position: 'top',
      labels: {
        font: { size: 11 },
        color: '#e5e7eb',
        usePointStyle: true,
      },
    },
    tooltip: {
      mode: 'index',
      intersect: false,
      backgroundColor: '#111827',
      titleColor: '#ffffff',
      bodyColor: '#e5e7eb',
      borderColor: 'rgba(255,255,255,0.08)',
      borderWidth: 1,
    },
  },
  scales: {
    x: {
      grid: { color: 'rgba(255, 255, 255, 0.03)' },
      title: {
        display: true,
        text: '연합 학습 라운드 (Global Rounds)',
        font: { size: 11 },
      },
    },
    yAccuracy: {
      type: 'linear',
      position: 'left',
      min: 0,
      max: 100,
      grid: { color: 'rgba(255, 255, 255, 0.03)' },
      title: {
        display: true,
        text: '모델 정확도 (%)',
        font: { size: 11 },
      },
    },
    yLoss: {
      type: 'linear',
      position: 'right',
      min: 0,
      max: 2.5,
      grid: { drawOnChartArea: false },
      title: {
        display: true,
        text: '오차값 (Loss)',
        font: { size: 11 },
      },
    },
  },
}

export function PerformanceChart() {
  const chartPoints = useSimulationStore((s) => s.chartPoints)
  const isRunning = useSimulationStore((s) => s.isRunning)
  const chartRef = useRef<ChartJS<'line'>>(null)

  const showPreview = chartPoints.length <= 1 && !isRunning

  const data = useMemo(() => {
    const labels = showPreview
      ? CHART_PREVIEW_POINTS.map((p) => p.round)
      : chartPoints.map((p) => p.round)

    const datasets = [
      {
        label: '글로벌 모델 정확도 (%)',
        data: showPreview
          ? CHART_PREVIEW_POINTS.map((p) => p.accuracy)
          : chartPoints.map((p) => p.accuracy),
        borderColor: showPreview ? 'rgba(6, 182, 212, 0.35)' : '#06b6d4',
        backgroundColor: showPreview ? 'rgba(6, 182, 212, 0.04)' : 'rgba(6, 182, 212, 0.15)',
        borderWidth: showPreview ? 1.5 : 2.5,
        borderDash: showPreview ? ([6, 4] as number[]) : undefined,
        fill: true,
        tension: 0.35,
        showLine: true,
        spanGaps: false,
        pointRadius: showPreview ? 3 : 5,
        pointHoverRadius: 7,
        pointBackgroundColor: showPreview ? 'rgba(6, 182, 212, 0.45)' : '#06b6d4',
        pointBorderColor: 'rgba(255, 255, 255, 0.25)',
        pointBorderWidth: 1,
        yAxisID: 'yAccuracy',
      },
      {
        label: '글로벌 Loss',
        data: showPreview
          ? CHART_PREVIEW_POINTS.map((p) => p.loss)
          : chartPoints.map((p) => p.loss),
        borderColor: showPreview ? 'rgba(239, 68, 68, 0.35)' : '#ef4444',
        backgroundColor: showPreview ? 'rgba(239, 68, 68, 0.03)' : 'rgba(239, 68, 68, 0.08)',
        borderWidth: showPreview ? 1.5 : 2.5,
        borderDash: showPreview ? ([6, 4] as number[]) : undefined,
        fill: true,
        tension: 0.35,
        showLine: true,
        spanGaps: false,
        pointRadius: showPreview ? 3 : 5,
        pointHoverRadius: 7,
        pointBackgroundColor: showPreview ? 'rgba(239, 68, 68, 0.45)' : '#ef4444',
        pointBorderColor: 'rgba(255, 255, 255, 0.25)',
        pointBorderWidth: 1,
        yAxisID: 'yLoss',
      },
    ]

    if (showPreview) {
      datasets[0] = { ...datasets[0], label: '예상 정확도 추이 (미리보기)' }
      datasets[1] = { ...datasets[1], label: '예상 Loss 추이 (미리보기)' }
    }

    return { labels, datasets }
  }, [chartPoints, showPreview])

  // Analytics 탭 마운트·데이터 갱신 시 Chart.js 캔버스 크기를 재계산한다.
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      chartRef.current?.resize()
      chartRef.current?.update('none')
    })
    return () => window.cancelAnimationFrame(frame)
  }, [chartPoints, showPreview])

  return (
    <div className="analytics-chart-box">
      <Line ref={chartRef} data={data} options={CHART_OPTIONS} />
    </div>
  )
}
