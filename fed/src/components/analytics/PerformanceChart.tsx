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
import { useMemo } from 'react'
import { Line } from 'react-chartjs-2'
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
  plugins: {
    legend: {
      position: 'top',
      labels: {
        font: { size: 11 },
        color: '#e5e7eb',
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

  const data = useMemo(
    () => ({
      labels: chartPoints.map((p) => p.round),
      datasets: [
        {
          label: '글로벌 모델 정확도 (%)',
          data: chartPoints.map((p) => p.accuracy),
          borderColor: '#06b6d4',
          backgroundColor: 'rgba(6, 182, 212, 0.08)',
          borderWidth: 2,
          tension: 0.3,
          pointBackgroundColor: '#06b6d4',
          pointBorderColor: 'rgba(255, 255, 255, 0.2)',
          pointHoverRadius: 6,
          yAxisID: 'yAccuracy',
        },
        {
          label: '글로벌 Loss',
          data: chartPoints.map((p) => p.loss),
          borderColor: '#ef4444',
          backgroundColor: 'rgba(239, 68, 68, 0.04)',
          borderWidth: 2,
          tension: 0.3,
          pointBackgroundColor: '#ef4444',
          pointBorderColor: 'rgba(255, 255, 255, 0.2)',
          pointHoverRadius: 6,
          yAxisID: 'yLoss',
        },
      ],
    }),
    [chartPoints],
  )

  return (
    <div className="analytics-chart-box">
      <Line data={data} options={CHART_OPTIONS} />
    </div>
  )
}
